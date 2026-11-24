"""Invoicing: GST tax invoices (document vs payment state, ADR-0011), credit and debit notes."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, String, Text, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from manima.core.audit import audit, emit
from manima.core.idempotency import run_idempotent
from manima.core.security import Ctx, require
from manima.modules.compliance_gst.domain import SCENARIOS, STATES, validate_gstin
from manima.modules.compliance_gst.models import DocTotalsMixin, TaxLineMixin
from manima.modules.compliance_gst.service import get_registration, next_number, supplier_state
from manima.modules.crm.module import Account, get_account
from manima.modules.documents import LineInput, build, line_dicts, lines_as_input, resolve_lines
from manima.modules.sales.module import SalesOrder, SalesOrderLine
from manima.shared.crud import get_or_404, ref_or_422
from manima.shared.db import Base, Money, TenantMixin, tenant_args, tfk, uuid7
from manima.shared.http import AppError, PageParams, paginate
from manima.shared.money import ZERO, r2
from manima.shared.schemas import Entity


# =============================================================== domain (pure)
def derive_payment_status(net_total: Decimal, paid: Decimal) -> str:
    if paid <= 0:
        return "unpaid" if net_total > 0 else "paid"
    if paid < net_total:
        return "partially_paid"
    if paid == net_total:
        return "paid"
    return "overpaid"


# =============================================================== models
class Invoice(TenantMixin, DocTotalsMixin, Base):
    __tablename__ = "invoices"
    document_type: Mapped[str] = mapped_column(String(20), default="tax_invoice")
    scenario: Mapped[str] = mapped_column(String(20), default="b2b")
    number: Mapped[str | None] = mapped_column(String(16))
    number_series_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    financial_year: Mapped[str | None] = mapped_column(String(7))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    gst_registration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    recipient_name: Mapped[str] = mapped_column(String(200))
    recipient_gstin: Mapped[str | None] = mapped_column(String(15))
    billing_address: Mapped[dict] = mapped_column(JSONB, default=dict)
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    document_status: Mapped[str] = mapped_column(String(12), default="draft")
    payment_status: Mapped[str] = mapped_column(String(16), default="unpaid")
    credit_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    debit_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    amount_due: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    irn: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = tenant_args(
        tfk("account_id", "accounts"),
        tfk("gst_registration_id", "gst_registrations"),
        tfk("sales_order_id", "sales_orders"),
        tfk("number_series_id", "number_series"),
        UniqueConstraint("tenant_id", "gst_registration_id", "document_type", "financial_year", "number"),
        CheckConstraint("document_status in ('draft','issued','cancelled')", name="document_status"),
        CheckConstraint(
            "payment_status in ('unpaid','partially_paid','paid','overpaid')", name="payment_status"
        ),
        CheckConstraint("document_type in ('tax_invoice','bill_of_supply')", name="document_type"),
        CheckConstraint(f"scenario in {SCENARIOS}", name="scenario"),
        CheckConstraint("document_status = 'draft' or number is not null", name="issued_has_number"),
    )


class InvoiceLine(TenantMixin, TaxLineMixin, Base):
    __tablename__ = "invoice_lines"
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    __table_args__ = tenant_args(
        tfk("invoice_id", "invoices", "CASCADE"),
        tfk("item_id", "items"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )


NOTE_REASONS = {
    "credit_note": ("sales_return", "post_sale_discount", "deficiency_in_service", "correction", "other"),
    "debit_note": ("price_increase", "additional_charges", "correction", "other"),
}


class AdjustmentNote(TenantMixin, DocTotalsMixin, Base):
    """Credit notes and debit notes (GST s.34) against an issued invoice."""

    __tablename__ = "adjustment_notes"
    note_type: Mapped[str] = mapped_column(String(12))
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    number: Mapped[str | None] = mapped_column(String(16))
    note_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(Text)
    document_status: Mapped[str] = mapped_column(String(12), default="draft")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        tfk("invoice_id", "invoices"),
        tfk("account_id", "accounts"),
        CheckConstraint("note_type in ('credit_note','debit_note')", name="note_type"),
        CheckConstraint("document_status in ('draft','issued','cancelled')", name="document_status"),
    )


class AdjustmentNoteLine(TenantMixin, TaxLineMixin, Base):
    __tablename__ = "adjustment_note_lines"
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    __table_args__ = tenant_args(
        tfk("note_id", "adjustment_notes", "CASCADE"),
        tfk("item_id", "items"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )


# =============================================================== public service
def net_total(inv: Invoice) -> Decimal:
    return (inv.grand_total or ZERO) + (inv.debit_total or ZERO) - (inv.credit_total or ZERO)


def refresh_payment_state(db: Session, inv: Invoice, paid: Decimal) -> None:
    """Called by payments (same transaction) after allocations change."""
    inv.amount_paid = r2(paid)
    inv.amount_due = r2(net_total(inv) - paid)
    inv.payment_status = derive_payment_status(net_total(inv), paid)


def _paid_amount(db: Session, inv: Invoice) -> Decimal:
    from manima.modules.payments.module import allocated_to_invoice

    return allocated_to_invoice(db, inv.tenant_id, inv.id)


router = APIRouter(prefix="/api/v1/billing", tags=["invoicing"])


class InvoiceIn(BaseModel):
    account_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    gst_registration_id: uuid.UUID | None = None
    scenario: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    place_of_supply: str | None = None
    recipient_gstin: str | None = None
    reverse_charge: bool = False
    lines: list[LineInput] = Field(default_factory=list, max_length=300)
    notes: str | None = Field(None, max_length=4000)
    terms: str | None = Field(None, max_length=4000)
    version: int | None = None

    @field_validator("scenario")
    @classmethod
    def _sc(cls, v):
        if v and v not in SCENARIOS:
            raise ValueError("Unknown GST scenario.")
        return v


class InvoiceOut(Entity):
    document_type: str
    scenario: str
    number: str | None
    invoice_date: date
    due_date: date | None
    gst_registration_id: uuid.UUID | None
    account_id: uuid.UUID
    recipient_name: str
    recipient_gstin: str | None
    billing_address: dict
    place_of_supply: str | None
    reverse_charge: bool
    document_status: str
    payment_status: str
    subtotal: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    cess_total: Decimal
    tax_total: Decimal
    round_off: Decimal
    grand_total: Decimal
    credit_total: Decimal
    debit_total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    sales_order_id: uuid.UUID | None
    notes: str | None
    terms: str | None
    issued_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None


def _inv_out(db: Session, inv: Invoice, with_lines: bool = True) -> dict:
    out = InvoiceOut.model_validate(inv).model_dump()
    out["overdue"] = bool(
        inv.document_status == "issued"
        and inv.amount_due > 0
        and inv.due_date
        and inv.due_date < date.today()
    )
    if with_lines:
        out["lines"] = line_dicts(
            db.scalars(
                select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no)
            )
        )
        from manima.modules.payments.module import allocations_for_invoice

        out["payments"] = allocations_for_invoice(db, inv.tenant_id, inv.id)
        out["notes_list"] = [
            {
                "id": n.id,
                "note_type": n.note_type,
                "number": n.number,
                "grand_total": n.grand_total,
                "document_status": n.document_status,
                "note_date": n.note_date,
            }
            for n in db.scalars(
                select(AdjustmentNote)
                .where(AdjustmentNote.invoice_id == inv.id)
                .order_by(AdjustmentNote.created_at)
            )
        ]
        from manima.modules.compliance_gst.models import GstRegistration

        reg = db.get(GstRegistration, inv.gst_registration_id) if inv.gst_registration_id else None
        out["supplier"] = (
            None
            if reg is None
            else {
                "gstin": reg.gstin,
                "legal_name": reg.legal_name,
                "trade_name": reg.trade_name,
                "state_code": reg.state_code,
                "address": reg.address,
            }
        )
    return out


def _fill_invoice(db: Session, ctx: Ctx, inv: Invoice, body: InvoiceIn) -> list:
    so = None
    if body.sales_order_id:
        so = ref_or_422(db, SalesOrder, body.sales_order_id, ctx.tenant_id, "sales_order_id", "Sales order")
        if so.status == "cancelled":
            raise AppError(409, "INVALID_TRANSITION", "Cancelled orders cannot be invoiced.")
        if so.invoice_id and so.invoice_id != inv.id:
            raise AppError(409, "ALREADY_INVOICED", "This order already has an invoice.")
    acc = get_account(db, ctx.tenant_id, body.account_id or (so.account_id if so else None))
    lines = body.lines
    if not lines and so is not None:
        lines = lines_as_input(
            db.scalars(
                select(SalesOrderLine)
                .where(SalesOrderLine.sales_order_id == so.id)
                .order_by(SalesOrderLine.line_no)
            )
        )
    if not lines:
        raise AppError(
            422, "VALIDATION_FAILED", "Add at least one line.", [{"field": "lines", "issue": "required"}]
        )
    pos = body.place_of_supply or (so.place_of_supply if so else None) or acc.state_code
    if pos and pos not in STATES:
        raise AppError(
            422,
            "VALIDATION_FAILED",
            "Unknown place of supply.",
            [{"field": "place_of_supply", "issue": "invalid"}],
        )
    gstin = body.recipient_gstin or acc.gstin or None
    scenario = body.scenario or ("b2b" if gstin else "b2c")
    reg = get_registration(
        db, ctx.tenant_id, body.gst_registration_id or (so.gst_registration_id if so else None)
    )
    inv.account_id, inv.sales_order_id = acc.id, so.id if so else None
    inv.gst_registration_id = reg.id if reg else None
    inv.scenario, inv.place_of_supply, inv.reverse_charge = scenario, pos, body.reverse_charge
    inv.recipient_name, inv.recipient_gstin = acc.name, gstin.upper() if gstin else None
    inv.billing_address = acc.billing_address or {}
    inv.invoice_date = body.invoice_date or date.today()
    inv.due_date = body.due_date or (inv.invoice_date + timedelta(days=acc.payment_terms_days))
    inv.notes, inv.terms = body.notes, body.terms
    composition = bool(reg and reg.registration_type == "composition")
    inv.document_type = "bill_of_supply" if composition else "tax_invoice"
    resolved = resolve_lines(db, ctx.tenant_id, lines)
    rows = build(
        inv,
        InvoiceLine,
        "invoice_id",
        resolved,
        supplier_state=supplier_state(db, ctx.tenant_id, reg),
        place_of_supply=pos,
        scenario=scenario,
        composition=composition,
    )
    inv.amount_due = net_total(inv)
    return rows


def validate_for_issue(db: Session, inv: Invoice) -> None:
    """GST-04 scenario checks before an invoice can be issued."""
    errs = []
    if inv.gst_registration_id is None:
        errs.append(
            {
                "field": "gst_registration_id",
                "issue": "required",
                "message": "Add your GST registration in Settings → GST before issuing invoices.",
            }
        )
    if inv.scenario in ("b2b", "sez_with_tax", "sez_lut"):
        if not inv.recipient_gstin:
            errs.append(
                {
                    "field": "recipient_gstin",
                    "issue": "required_for_scenario",
                    "scenario": inv.scenario,
                    "message": "Recipient GSTIN is required for a B2B invoice.",
                }
            )
        elif validate_gstin(inv.recipient_gstin):
            errs.append(
                {
                    "field": "recipient_gstin",
                    "issue": "invalid",
                    "message": validate_gstin(inv.recipient_gstin),
                }
            )
    if not inv.place_of_supply:
        errs.append(
            {"field": "place_of_supply", "issue": "required", "message": "Place of supply is required."}
        )
    if inv.grand_total <= 0:
        errs.append(
            {"field": "lines", "issue": "zero_total", "message": "Invoice total must be greater than zero."}
        )
    if errs:
        raise AppError(422, "GST_SCENARIO_INVALID", errs[0]["message"], errs)


@router.get("/invoices")
def list_invoices(
    params: PageParams = Depends(),
    document_status: str | None = None,
    payment_status: str | None = None,
    account_id: uuid.UUID | None = None,
    overdue: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: Ctx = Depends(require("invoicing.invoice.read")),
):
    q = select(Invoice).where(Invoice.tenant_id == ctx.tenant_id)
    if document_status:
        q = q.where(Invoice.document_status.in_(document_status.split(",")))
    if payment_status:
        q = q.where(Invoice.payment_status.in_(payment_status.split(",")))
    if account_id:
        q = q.where(Invoice.account_id == account_id)
    if overdue:
        q = q.where(
            Invoice.document_status == "issued", Invoice.amount_due > 0, Invoice.due_date < date.today()
        )
    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(Invoice.number, Invoice.recipient_name, Invoice.recipient_gstin),
        sortable={
            "invoice_date": Invoice.invoice_date,
            "grand_total": Invoice.grand_total,
            "due_date": Invoice.due_date,
            "amount_due": Invoice.amount_due,
        },
        default_sort=Invoice.created_at.desc(),
    )
    page["data"] = [_inv_out(ctx.db, i, with_lines=False) for i in page["data"]]
    return page


@router.post("/invoices", status_code=201)
def create_invoice(
    body: InvoiceIn,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("invoicing.invoice.create")),
):
    def do():
        db = ctx.db
        inv = Invoice(
            tenant_id=ctx.tenant_id, created_by=ctx.user.id, recipient_name="", invoice_date=date.today()
        )
        inv.id = uuid7()
        rows = _fill_invoice(db, ctx, inv, body)
        db.add(inv)
        db.flush()
        db.add_all(rows)
        if inv.sales_order_id:
            db.get(SalesOrder, inv.sales_order_id).invoice_id = inv.id
        db.flush()
        audit(db, ctx, "invoice.created", "invoice", inv.id, after={"grand_total": inv.grand_total})
        return _inv_out(db, inv)

    return run_idempotent(ctx, idempotency_key, "invoicing.invoice.create", body.model_dump(mode="json"), do)


@router.get("/invoices/{iid}")
def get_invoice(iid: uuid.UUID, ctx: Ctx = Depends(require("invoicing.invoice.read"))):
    return _inv_out(ctx.db, get_or_404(ctx.db, Invoice, iid, ctx.tenant_id, "Invoice"))


@router.patch("/invoices/{iid}")
def update_invoice(iid: uuid.UUID, body: InvoiceIn, ctx: Ctx = Depends(require("invoicing.invoice.create"))):
    db = ctx.db
    inv = get_or_404(db, Invoice, iid, ctx.tenant_id, "Invoice", lock=True)
    if inv.document_status != "draft":
        raise AppError(
            409, "INVALID_TRANSITION", "Issued invoices cannot be edited; use a credit or debit note."
        )
    if body.version is not None and body.version != inv.version:
        raise AppError(409, "VERSION_CONFLICT", "This invoice changed. Reload and retry.")
    old_so = inv.sales_order_id
    db.execute(InvoiceLine.__table__.delete().where(InvoiceLine.invoice_id == inv.id))
    rows = _fill_invoice(db, ctx, inv, body)
    db.add_all(rows)
    if old_so and old_so != inv.sales_order_id:
        db.get(SalesOrder, old_so).invoice_id = None
    if inv.sales_order_id:
        db.get(SalesOrder, inv.sales_order_id).invoice_id = inv.id
    inv.version += 1
    db.flush()
    audit(db, ctx, "invoice.updated", "invoice", inv.id, after={"grand_total": inv.grand_total})
    db.commit()
    return _inv_out(db, inv)


@router.post("/invoices/{iid}:issue")
def issue_invoice(
    iid: uuid.UUID,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("invoicing.invoice.issue")),
):
    """Lock series, assign number, document_status=issued — one transaction (SCHEMA_DESIGN §6)."""

    def do():
        db = ctx.db
        inv = get_or_404(db, Invoice, iid, ctx.tenant_id, "Invoice", lock=True)
        if inv.document_status != "draft":
            raise AppError(409, "INVALID_TRANSITION", f"Invoice is already {inv.document_status}.")
        validate_for_issue(db, inv)
        from manima.modules.compliance_gst.domain import financial_year
        from manima.modules.compliance_gst.service import fy_start_month

        inv.number, inv.number_series_id = next_number(
            db, ctx.tenant_id, inv.document_type, inv.invoice_date, inv.gst_registration_id
        )
        inv.financial_year = financial_year(inv.invoice_date, fy_start_month(db, ctx.tenant_id))
        inv.document_status, inv.issued_at = "issued", datetime.now(UTC)
        refresh_payment_state(db, inv, _paid_amount(db, inv))
        audit(
            db,
            ctx,
            "invoice.issued",
            "invoice",
            inv.id,
            before={"document_status": "draft"},
            after={"number": inv.number, "grand_total": inv.grand_total},
        )
        emit(
            db,
            ctx.tenant_id,
            "invoice.issued",
            "invoice",
            inv.id,
            {"number": inv.number, "grand_total": str(inv.grand_total), "account_id": str(inv.account_id)},
        )
        return _inv_out(db, inv)

    return run_idempotent(ctx, idempotency_key, f"invoicing.invoice.issue:{iid}", {"iid": str(iid)}, do)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/invoices/{iid}:cancel")
def cancel_invoice(iid: uuid.UUID, body: CancelIn, ctx: Ctx = Depends(require("invoicing.invoice.cancel"))):
    db = ctx.db
    inv = get_or_404(db, Invoice, iid, ctx.tenant_id, "Invoice", lock=True)
    if inv.document_status != "issued":
        raise AppError(409, "INVALID_TRANSITION", "Only issued invoices can be cancelled.")
    if _paid_amount(db, inv) > 0:
        raise AppError(409, "HAS_PAYMENTS", "Remove payment allocations before cancelling this invoice.")
    if db.scalar(
        select(AdjustmentNote.id).where(
            AdjustmentNote.invoice_id == inv.id, AdjustmentNote.document_status == "issued"
        )
    ):
        raise AppError(409, "HAS_NOTES", "This invoice has issued credit/debit notes.")
    inv.document_status, inv.cancelled_at, inv.cancel_reason = "cancelled", datetime.now(UTC), body.reason
    inv.amount_due = ZERO
    if inv.sales_order_id:
        so = db.get(SalesOrder, inv.sales_order_id)
        if so and so.invoice_id == inv.id:
            so.invoice_id = None
    audit(
        db,
        ctx,
        "invoice.cancelled",
        "invoice",
        inv.id,
        before={"document_status": "issued"},
        after={"document_status": "cancelled", "reason": body.reason},
    )
    emit(db, ctx.tenant_id, "invoice.cancelled", "invoice", inv.id, {"number": inv.number})
    db.commit()
    return _inv_out(db, inv)


@router.delete("/invoices/{iid}")
def delete_invoice(iid: uuid.UUID, ctx: Ctx = Depends(require("invoicing.invoice.create"))):
    db = ctx.db
    inv = get_or_404(db, Invoice, iid, ctx.tenant_id, "Invoice")
    if inv.document_status != "draft":
        raise AppError(
            409, "INVALID_TRANSITION", "Only drafts can be deleted; cancel issued invoices instead."
        )
    if inv.sales_order_id:
        so = db.get(SalesOrder, inv.sales_order_id)
        if so:
            so.invoice_id = None
    audit(db, ctx, "invoice.deleted", "invoice", inv.id)
    db.delete(inv)
    db.commit()
    return {"ok": True}


# =============================================================== credit / debit notes
class NoteIn(BaseModel):
    invoice_id: uuid.UUID
    reason: str
    note_date: date | None = None
    description: str | None = Field(None, max_length=2000)
    lines: list[LineInput] = Field(min_length=1, max_length=100)


class NoteOut(Entity):
    note_type: str
    invoice_id: uuid.UUID
    account_id: uuid.UUID
    number: str | None
    note_date: date
    reason: str
    description: str | None
    document_status: str
    place_of_supply: str | None
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    issued_at: datetime | None


def _note_out(db: Session, n: AdjustmentNote, with_lines: bool = True) -> dict:
    out = NoteOut.model_validate(n).model_dump()
    inv = db.get(Invoice, n.invoice_id)
    out["invoice_number"] = inv.number if inv else None
    out["account_name"] = inv.recipient_name if inv else None
    if with_lines:
        out["lines"] = line_dicts(
            db.scalars(
                select(AdjustmentNoteLine)
                .where(AdjustmentNoteLine.note_id == n.id)
                .order_by(AdjustmentNoteLine.line_no)
            )
        )
    return out


def _notes_router(note_type: str, path: str) -> None:
    label = "Credit note" if note_type == "credit_note" else "Debit note"

    @router.get(f"/{path}", name=f"list_{note_type}")
    def list_notes(
        params: PageParams = Depends(),
        invoice_id: uuid.UUID | None = None,
        document_status: str | None = None,
        ctx: Ctx = Depends(require("invoicing.note.read")),
    ):
        q = select(AdjustmentNote).where(
            AdjustmentNote.tenant_id == ctx.tenant_id, AdjustmentNote.note_type == note_type
        )
        if invoice_id:
            q = q.where(AdjustmentNote.invoice_id == invoice_id)
        if document_status:
            q = q.where(AdjustmentNote.document_status == document_status)
        page = paginate(
            ctx.db,
            q,
            params,
            search_cols=(AdjustmentNote.number, AdjustmentNote.reason),
            default_sort=AdjustmentNote.created_at.desc(),
        )
        page["data"] = [_note_out(ctx.db, n, False) for n in page["data"]]
        return page

    @router.post(f"/{path}", status_code=201, name=f"create_{note_type}")
    def create_note(
        body: NoteIn,
        idempotency_key: str | None = Header(None),
        ctx: Ctx = Depends(require("invoicing.note.create")),
    ):
        def do():
            db = ctx.db
            if body.reason not in NOTE_REASONS[note_type]:
                raise AppError(
                    422, "VALIDATION_FAILED", "Invalid reason.", [{"field": "reason", "issue": "invalid"}]
                )
            inv = ref_or_422(db, Invoice, body.invoice_id, ctx.tenant_id, "invoice_id", "Invoice")
            if inv.document_status != "issued":
                raise AppError(409, "INVALID_TRANSITION", "Notes can only be raised against issued invoices.")
            n = AdjustmentNote(
                tenant_id=ctx.tenant_id,
                created_by=ctx.user.id,
                note_type=note_type,
                invoice_id=inv.id,
                account_id=inv.account_id,
                note_date=body.note_date or date.today(),
                reason=body.reason,
                description=body.description,
                place_of_supply=inv.place_of_supply,
            )
            n.id = uuid7()
            reg = get_registration(db, ctx.tenant_id, inv.gst_registration_id)
            resolved = resolve_lines(db, ctx.tenant_id, body.lines)
            rows = build(
                n,
                AdjustmentNoteLine,
                "note_id",
                resolved,
                supplier_state=supplier_state(db, ctx.tenant_id, reg),
                place_of_supply=inv.place_of_supply,
                scenario=inv.scenario,
                composition=inv.document_type == "bill_of_supply",
            )
            if note_type == "credit_note" and n.grand_total > net_total(inv):
                raise AppError(
                    422, "CREDIT_EXCEEDS_INVOICE", "Credit note cannot exceed the invoice's net total."
                )
            db.add(n)
            db.flush()
            db.add_all(rows)
            db.flush()
            audit(
                db,
                ctx,
                f"{note_type}.created",
                note_type,
                n.id,
                after={"invoice": inv.number, "total": n.grand_total},
            )
            return _note_out(db, n)

        return run_idempotent(
            ctx, idempotency_key, f"invoicing.{note_type}.create", body.model_dump(mode="json"), do
        )

    @router.get(f"/{path}/{{nid}}", name=f"get_{note_type}")
    def get_note(nid: uuid.UUID, ctx: Ctx = Depends(require("invoicing.note.read"))):
        n = get_or_404(ctx.db, AdjustmentNote, nid, ctx.tenant_id, label)
        if n.note_type != note_type:
            raise AppError(404, "NOT_FOUND", f"{label} not found.")
        return _note_out(ctx.db, n)

    @router.post(f"/{path}/{{nid}}:issue", name=f"issue_{note_type}")
    def issue_note(nid: uuid.UUID, ctx: Ctx = Depends(require("invoicing.note.issue"))):
        db = ctx.db
        n = get_or_404(db, AdjustmentNote, nid, ctx.tenant_id, label, lock=True)
        if n.note_type != note_type or n.document_status != "draft":
            raise AppError(409, "INVALID_TRANSITION", f"{label} is not a draft.")
        inv = db.get(Invoice, n.invoice_id, with_for_update=True)
        if inv.document_status != "issued":
            raise AppError(409, "INVALID_TRANSITION", "The invoice is no longer issued.")
        if note_type == "credit_note" and n.grand_total > net_total(inv):
            raise AppError(
                422, "CREDIT_EXCEEDS_INVOICE", "Credit note cannot exceed the invoice's net total."
            )
        n.number, _ = next_number(db, ctx.tenant_id, note_type, n.note_date, inv.gst_registration_id)
        n.document_status, n.issued_at = "issued", datetime.now(UTC)
        if note_type == "credit_note":
            inv.credit_total += n.grand_total
        else:
            inv.debit_total += n.grand_total
        refresh_payment_state(db, inv, _paid_amount(db, inv))
        audit(
            db, ctx, f"{note_type}.issued", note_type, n.id, after={"number": n.number, "invoice": inv.number}
        )
        emit(
            db,
            ctx.tenant_id,
            f"{note_type}.issued",
            note_type,
            n.id,
            {"number": n.number, "invoice_id": str(inv.id)},
        )
        db.commit()
        return _note_out(db, n)

    @router.delete(f"/{path}/{{nid}}", name=f"delete_{note_type}")
    def delete_note(nid: uuid.UUID, ctx: Ctx = Depends(require("invoicing.note.create"))):
        n = get_or_404(ctx.db, AdjustmentNote, nid, ctx.tenant_id, label)
        if n.note_type != note_type or n.document_status != "draft":
            raise AppError(409, "INVALID_TRANSITION", "Only drafts can be deleted.")
        audit(ctx.db, ctx, f"{note_type}.deleted", note_type, n.id)
        ctx.db.delete(n)
        ctx.db.commit()
        return {"ok": True}


_notes_router("credit_note", "credit-notes")
_notes_router("debit_note", "debit-notes")


@router.get("/note-reasons")
def note_reasons():
    return {k: list(v) for k, v in NOTE_REASONS.items()}


_ = (func, Account)
