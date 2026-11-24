"""Sales: quotations (versioning, discount approval, send, accept) and sales orders (reserve, deliver)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from manima.core.audit import audit, emit, notify
from manima.core.idempotency import run_idempotent
from manima.core.models import TenantSettings
from manima.core.routes_tenant import notify_members_with
from manima.core.security import Ctx, require
from manima.modules.compliance_gst.domain import STATES
from manima.modules.compliance_gst.models import DocTotalsMixin, TaxLineMixin
from manima.modules.compliance_gst.service import get_registration, next_number, supplier_state
from manima.modules.crm.module import Account, Contact, Opportunity, get_account
from manima.modules.documents import LineInput, build, line_dicts, lines_as_input, resolve_lines
from manima.modules.inventory.module import (
    Warehouse,
    default_warehouse,
    move_stock,
    release_reservations,
    reserve,
)
from manima.shared.crud import get_or_404, ref_or_422
from manima.shared.db import SCHEMA, Base, Qty, TenantMixin, tenant_args, tfk, uuid7
from manima.shared.http import AppError, PageParams, paginate
from manima.shared.money import ZERO
from manima.shared.schemas import Entity

Q_STATUSES = ("draft", "sent", "accepted", "rejected", "expired", "superseded", "converted")


class Quotation(TenantMixin, DocTotalsMixin, Base):
    __tablename__ = "quotations"
    number: Mapped[str | None] = mapped_column(String(30))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    parent_quotation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    gst_registration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    approval_status: Mapped[str] = mapped_column(String(12), default="not_required")
    issue_date: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    terms: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.platform_users.id"), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        tfk("account_id", "accounts"),
        tfk("contact_id", "contacts"),
        tfk("opportunity_id", "opportunities"),
        tfk("gst_registration_id", "gst_registrations"),
        tfk("parent_quotation_id", "quotations"),
        CheckConstraint(f"status in {Q_STATUSES}", name="status"),
        CheckConstraint(
            "approval_status in ('not_required','pending','approved','rejected')", name="approval_status"
        ),
    )


class QuotationLine(TenantMixin, TaxLineMixin, Base):
    __tablename__ = "quotation_lines"
    quotation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    __table_args__ = tenant_args(
        tfk("quotation_id", "quotations", "CASCADE"),
        tfk("item_id", "items"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )


SO_STATUSES = ("draft", "confirmed", "delivered", "cancelled")


class SalesOrder(TenantMixin, DocTotalsMixin, Base):
    __tablename__ = "sales_orders"
    number: Mapped[str] = mapped_column(String(30))
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    gst_registration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    order_date: Mapped[date] = mapped_column(Date)
    expected_delivery: Mapped[date | None] = mapped_column(Date)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_po: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.platform_users.id"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = tenant_args(
        tfk("account_id", "accounts"),
        tfk("quotation_id", "quotations"),
        tfk("warehouse_id", "warehouses"),
        tfk("gst_registration_id", "gst_registrations"),
        CheckConstraint(f"status in {SO_STATUSES}", name="status"),
    )


class SalesOrderLine(TenantMixin, TaxLineMixin, Base):
    __tablename__ = "sales_order_lines"
    sales_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    delivered_qty: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    __table_args__ = tenant_args(
        tfk("sales_order_id", "sales_orders", "CASCADE"),
        tfk("item_id", "items"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )


router = APIRouter(prefix="/api/v1/sales", tags=["sales"])


# =============================================================== shared
class DocIn(BaseModel):
    account_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    gst_registration_id: uuid.UUID | None = None
    place_of_supply: str | None = None
    lines: list[LineInput] = Field(min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=4000)


def _place_of_supply(db: Session, ctx: Ctx, acc: Account, pos: str | None) -> str | None:
    if pos and pos not in STATES:
        raise AppError(
            422,
            "VALIDATION_FAILED",
            "Unknown place of supply.",
            [{"field": "place_of_supply", "issue": "invalid"}],
        )
    if pos:
        return pos
    if acc.state_code:
        return acc.state_code
    s = db.get(TenantSettings, ctx.tenant_id)
    return s.state_code if s else None


def _price_doc(
    db: Session, ctx: Ctx, doc, line_model, fk: str, body_lines: list[LineInput], acc: Account
) -> list:
    reg = get_registration(db, ctx.tenant_id, doc.gst_registration_id)
    if reg and doc.gst_registration_id is None:
        doc.gst_registration_id = reg.id
    resolved = resolve_lines(db, ctx.tenant_id, body_lines)
    return build(
        doc,
        line_model,
        fk,
        resolved,
        supplier_state=supplier_state(db, ctx.tenant_id, reg),
        place_of_supply=doc.place_of_supply,
        scenario="b2b" if acc.gstin else "b2c",
        composition=bool(reg and reg.registration_type == "composition"),
    )


# =============================================================== quotations
class QuotationIn(DocIn):
    opportunity_id: uuid.UUID | None = None
    issue_date: date | None = None
    valid_until: date | None = None
    terms: str | None = Field(None, max_length=4000)


class QuotationPatch(QuotationIn):
    version: int | None = None


class QuotationOut(Entity):
    number: str | None
    revision: int
    parent_quotation_id: uuid.UUID | None
    account_id: uuid.UUID
    contact_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    gst_registration_id: uuid.UUID | None
    place_of_supply: str | None
    status: str
    approval_status: str
    issue_date: date
    valid_until: date | None
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
    terms: str | None
    notes: str | None
    owner_id: uuid.UUID | None
    sent_at: datetime | None


def _settings(db, tenant_id) -> TenantSettings:
    return db.get(TenantSettings, tenant_id)


def _needs_approval(db, ctx: Ctx, lines: list[LineInput]) -> bool:
    limit = _settings(db, ctx.tenant_id).discount_approval_limit
    return any(ln.discount_pct > limit for ln in lines)


def _q_out(db: Session, q: Quotation, with_lines: bool = True) -> dict:
    out = QuotationOut.model_validate(q).model_dump()
    acc = db.get(Account, q.account_id)
    out["account_name"] = acc.name if acc else None
    out["account_gstin"] = acc.gstin if acc else None
    out["billing_address"] = acc.billing_address if acc else {}
    if with_lines:
        lines = db.scalars(
            select(QuotationLine).where(QuotationLine.quotation_id == q.id).order_by(QuotationLine.line_no)
        )
        out["lines"] = line_dicts(lines)
        root = q.parent_quotation_id or q.id
        versions = db.scalars(
            select(Quotation)
            .where(
                Quotation.tenant_id == q.tenant_id,
                (Quotation.id == root) | (Quotation.parent_quotation_id == root),
            )
            .order_by(Quotation.revision)
        )
        out["revisions"] = [{"id": v.id, "revision": v.revision, "status": v.status} for v in versions]
    return out


def _q_guard(ctx: Ctx, q: Quotation) -> None:
    if ctx.own_only("sales.quotation") and q.owner_id != ctx.user.id:
        raise AppError(404, "NOT_FOUND", "Quotation not found.")


@router.get("/quotations")
def list_quotations(
    params: PageParams = Depends(),
    status: str | None = None,
    account_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(require("sales.quotation.read_all", "sales.quotation.read_own")),
):
    q = (
        select(Quotation)
        .join(Account, Account.id == Quotation.account_id)
        .where(Quotation.tenant_id == ctx.tenant_id, Quotation.status != "superseded")
    )
    if ctx.own_only("sales.quotation"):
        q = q.where(Quotation.owner_id == ctx.user.id)
    if status:
        q = q.where(Quotation.status.in_(status.split(",")))
    if account_id:
        q = q.where(Quotation.account_id == account_id)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(Quotation.number, Account.name),
        sortable={
            "issue_date": Quotation.issue_date,
            "grand_total": Quotation.grand_total,
            "created_at": Quotation.created_at,
        },
        default_sort=Quotation.created_at.desc(),
    )
    page["data"] = [_q_out(ctx.db, x, with_lines=False) for x in page["data"]]
    return page


def _fill_quotation(db: Session, ctx: Ctx, q: Quotation, body: QuotationIn) -> list:
    acc = get_account(db, ctx.tenant_id, body.account_id)
    ref_or_422(db, Contact, body.contact_id, ctx.tenant_id, "contact_id", "Contact")
    ref_or_422(db, Opportunity, body.opportunity_id, ctx.tenant_id, "opportunity_id", "Opportunity")
    s = _settings(db, ctx.tenant_id)
    q.account_id, q.contact_id, q.opportunity_id = acc.id, body.contact_id, body.opportunity_id
    q.gst_registration_id = body.gst_registration_id
    q.issue_date = body.issue_date or date.today()
    q.valid_until = body.valid_until or (q.issue_date + timedelta(days=s.quote_validity_days))
    if q.valid_until < q.issue_date:
        raise AppError(
            422,
            "VALIDATION_FAILED",
            "Valid-until must be after the issue date.",
            [{"field": "valid_until", "issue": "before_issue_date"}],
        )
    q.terms, q.notes = body.terms, body.notes
    q.place_of_supply = _place_of_supply(db, ctx, acc, body.place_of_supply)
    q.approval_status = "pending" if _needs_approval(db, ctx, body.lines) else "not_required"
    return _price_doc(db, ctx, q, QuotationLine, "quotation_id", body.lines, acc)


@router.post("/quotations", status_code=201)
def create_quotation(
    body: QuotationIn,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("sales.quotation.create")),
):
    def do():
        db = ctx.db
        q = Quotation(
            tenant_id=ctx.tenant_id, created_by=ctx.user.id, owner_id=ctx.user.id, issue_date=date.today()
        )
        q.id = uuid7()
        rows = _fill_quotation(db, ctx, q, body)
        db.add(q)
        db.flush()
        db.add_all(rows)
        db.flush()
        audit(db, ctx, "quotation.created", "quotation", q.id, after={"grand_total": q.grand_total})
        emit(db, ctx.tenant_id, "quote.created", "quotation", q.id, {"grand_total": str(q.grand_total)})
        if q.approval_status == "pending":
            notify_members_with(
                db,
                ctx.tenant_id,
                "sales.quotation.approve",
                "Quotation needs discount approval",
                f"{_q_out(db, q, False)['account_name']}: ₹{q.grand_total}",
                f"/sales/quotations/{q.id}",
                exclude=ctx.user.id,
            )
        return _q_out(db, q)

    return run_idempotent(ctx, idempotency_key, "sales.quotation.create", body.model_dump(mode="json"), do)


@router.get("/quotations/{qid}")
def get_quotation(
    qid: uuid.UUID, ctx: Ctx = Depends(require("sales.quotation.read_all", "sales.quotation.read_own"))
):
    q = get_or_404(ctx.db, Quotation, qid, ctx.tenant_id, "Quotation")
    _q_guard(ctx, q)
    return _q_out(ctx.db, q)


@router.patch("/quotations/{qid}")
def update_quotation(
    qid: uuid.UUID, body: QuotationPatch, ctx: Ctx = Depends(require("sales.quotation.update"))
):
    """Draft: edit in place. Sent: create a new revision (new row) and supersede the old one."""
    db = ctx.db
    q = get_or_404(db, Quotation, qid, ctx.tenant_id, "Quotation", lock=True)
    _q_guard(ctx, q)
    if body.version is not None and body.version != q.version:
        raise AppError(409, "VERSION_CONFLICT", "This quotation changed. Reload and retry.")
    if q.status == "draft":
        db.execute(QuotationLine.__table__.delete().where(QuotationLine.quotation_id == q.id))
        rows = _fill_quotation(db, ctx, q, body)
        db.add_all(rows)
        q.version += 1
        target = q
    elif q.status == "sent":
        root = q.parent_quotation_id or q.id
        new = Quotation(
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            owner_id=q.owner_id,
            parent_quotation_id=root,
            revision=q.revision + 1,
            number=q.number,
            issue_date=date.today(),
        )
        new.id = uuid7()
        rows = _fill_quotation(db, ctx, new, body)
        db.add(new)
        db.flush()
        db.add_all(rows)
        q.status = "superseded"
        target = new
    else:
        raise AppError(409, "INVALID_TRANSITION", f"A {q.status} quotation cannot be edited.")
    db.flush()
    audit(
        db,
        ctx,
        "quotation.updated",
        "quotation",
        target.id,
        before={"id": str(q.id), "revision": q.revision},
        after={"revision": target.revision, "grand_total": target.grand_total},
    )
    db.commit()
    return _q_out(db, target)


def _transition(ctx: Ctx, qid: uuid.UUID, allowed_from: tuple, to: str, action: str) -> Quotation:
    db = ctx.db
    q = get_or_404(db, Quotation, qid, ctx.tenant_id, "Quotation", lock=True)
    _q_guard(ctx, q)
    if q.status not in allowed_from:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot {action} a {q.status} quotation.")
    before = q.status
    q.status = to
    audit(db, ctx, f"quotation.{action}", "quotation", q.id, before={"status": before}, after={"status": to})
    return q


@router.post("/quotations/{qid}:send")
def send_quotation(qid: uuid.UUID, ctx: Ctx = Depends(require("sales.quotation.send"))):
    db = ctx.db
    q = get_or_404(db, Quotation, qid, ctx.tenant_id, "Quotation", lock=True)
    if q.approval_status in ("pending", "rejected"):
        raise AppError(409, "APPROVAL_REQUIRED", "Discount approval is required before sending.")
    q = _transition(ctx, qid, ("draft",), "sent", "sent")
    if not q.number:
        q.number, _ = next_number(db, ctx.tenant_id, "quotation", q.issue_date)
    q.sent_at = datetime.now(UTC)
    acc = db.get(Account, q.account_id)
    contact = db.get(Contact, q.contact_id) if q.contact_id else None
    emit(db, ctx.tenant_id, "quote.sent", "quotation", q.id, {"number": q.number})
    emit(
        db,
        ctx.tenant_id,
        "message.requested",
        "quotation",
        q.id,
        {
            "channel": "email",
            "to": (contact.email if contact else None) or acc.email,
            "template": "quotation",
            "number": q.number,
        },
    )
    db.commit()
    return _q_out(db, q)


class DecisionIn(BaseModel):
    note: str | None = Field(None, max_length=300)


@router.post("/quotations/{qid}:approve")
def approve_quotation(
    qid: uuid.UUID, body: DecisionIn | None = None, ctx: Ctx = Depends(require("sales.quotation.approve"))
):
    db = ctx.db
    q = get_or_404(db, Quotation, qid, ctx.tenant_id, "Quotation", lock=True)
    if q.approval_status != "pending":
        raise AppError(409, "INVALID_TRANSITION", "This quotation is not awaiting approval.")
    q.approval_status = "approved"
    audit(db, ctx, "quotation.approved", "quotation", q.id, after={"note": body.note if body else None})
    if q.owner_id and q.owner_id != ctx.user.id:
        notify(
            db,
            ctx.tenant_id,
            q.owner_id,
            "Quotation discount approved",
            None,
            f"/sales/quotations/{q.id}",
            "approval",
        )
    db.commit()
    return _q_out(db, q)


@router.post("/quotations/{qid}:reject-approval")
def reject_approval(
    qid: uuid.UUID, body: DecisionIn | None = None, ctx: Ctx = Depends(require("sales.quotation.approve"))
):
    db = ctx.db
    q = get_or_404(db, Quotation, qid, ctx.tenant_id, "Quotation", lock=True)
    if q.approval_status != "pending":
        raise AppError(409, "INVALID_TRANSITION", "This quotation is not awaiting approval.")
    q.approval_status = "rejected"
    audit(
        db, ctx, "quotation.approval_rejected", "quotation", q.id, after={"note": body.note if body else None}
    )
    if q.owner_id and q.owner_id != ctx.user.id:
        notify(
            db,
            ctx.tenant_id,
            q.owner_id,
            "Quotation discount rejected",
            body.note if body else None,
            f"/sales/quotations/{q.id}",
            "approval",
        )
    db.commit()
    return _q_out(db, q)


@router.post("/quotations/{qid}:accept")
def accept_quotation(qid: uuid.UUID, ctx: Ctx = Depends(require("sales.quotation.update"))):
    q = _transition(ctx, qid, ("sent",), "accepted", "accepted")
    q.responded_at = datetime.now(UTC)
    emit(ctx.db, ctx.tenant_id, "quote.accepted", "quotation", q.id, {"grand_total": str(q.grand_total)})
    ctx.db.commit()
    return _q_out(ctx.db, q)


@router.post("/quotations/{qid}:decline")
def decline_quotation(qid: uuid.UUID, ctx: Ctx = Depends(require("sales.quotation.update"))):
    q = _transition(ctx, qid, ("sent",), "rejected", "rejected")
    q.responded_at = datetime.now(UTC)
    ctx.db.commit()
    return _q_out(ctx.db, q)


@router.post("/quotations/{qid}:convert", status_code=201)
def convert_quotation(
    qid: uuid.UUID,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("sales.order.create")),
):
    def do():
        db = ctx.db
        q = get_or_404(db, Quotation, qid, ctx.tenant_id, "Quotation", lock=True)
        if q.status not in ("accepted", "sent"):
            raise AppError(409, "INVALID_TRANSITION", "Only sent or accepted quotations can be converted.")
        lines = db.scalars(
            select(QuotationLine).where(QuotationLine.quotation_id == q.id).order_by(QuotationLine.line_no)
        )
        body = OrderIn(
            account_id=q.account_id,
            gst_registration_id=q.gst_registration_id,
            place_of_supply=q.place_of_supply,
            lines=lines_as_input(lines),
            notes=q.notes,
        )
        so = _create_order(db, ctx, body, quotation_id=q.id)
        q.status = "converted"
        audit(db, ctx, "quotation.converted", "quotation", q.id, after={"sales_order_id": str(so.id)})
        return _so_out(db, so)

    return run_idempotent(ctx, idempotency_key, f"sales.quotation.convert:{qid}", {"qid": str(qid)}, do)


@router.delete("/quotations/{qid}")
def delete_quotation(qid: uuid.UUID, ctx: Ctx = Depends(require("sales.quotation.delete"))):
    q = get_or_404(ctx.db, Quotation, qid, ctx.tenant_id, "Quotation")
    if q.status != "draft" or q.number:
        raise AppError(409, "INVALID_TRANSITION", "Only unsent drafts can be deleted.")
    audit(ctx.db, ctx, "quotation.deleted", "quotation", q.id)
    ctx.db.delete(q)
    ctx.db.commit()
    return {"ok": True}


# =============================================================== sales orders
class OrderIn(DocIn):
    warehouse_id: uuid.UUID | None = None
    order_date: date | None = None
    expected_delivery: date | None = None
    customer_po: str | None = Field(None, max_length=60)


class SalesOrderOut(Entity):
    number: str
    quotation_id: uuid.UUID | None
    account_id: uuid.UUID
    gst_registration_id: uuid.UUID | None
    warehouse_id: uuid.UUID | None
    place_of_supply: str | None
    status: str
    order_date: date
    expected_delivery: date | None
    delivered_at: datetime | None
    customer_po: str | None
    notes: str | None
    invoice_id: uuid.UUID | None
    subtotal: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    tax_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    round_off: Decimal
    grand_total: Decimal


def _so_out(db: Session, so: SalesOrder, with_lines: bool = True) -> dict:
    out = SalesOrderOut.model_validate(so).model_dump()
    acc = db.get(Account, so.account_id)
    out["account_name"] = acc.name if acc else None
    if with_lines:
        lines = list(
            db.scalars(
                select(SalesOrderLine)
                .where(SalesOrderLine.sales_order_id == so.id)
                .order_by(SalesOrderLine.line_no)
            )
        )
        out["lines"] = [
            {**d, "delivered_qty": ln.delivered_qty} for d, ln in zip(line_dicts(lines), lines, strict=True)
        ]
    return out


def _create_order(db: Session, ctx: Ctx, body: OrderIn, quotation_id: uuid.UUID | None = None) -> SalesOrder:
    acc = get_account(db, ctx.tenant_id, body.account_id)
    wh = (
        ref_or_422(db, Warehouse, body.warehouse_id, ctx.tenant_id, "warehouse_id", "Warehouse")
        if body.warehouse_id
        else default_warehouse(db, ctx.tenant_id)
    )
    d = body.order_date or date.today()
    number, _ = next_number(db, ctx.tenant_id, "sales_order", d)
    so = SalesOrder(
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        owner_id=ctx.user.id,
        number=number,
        quotation_id=quotation_id,
        account_id=acc.id,
        gst_registration_id=body.gst_registration_id,
        warehouse_id=wh.id if wh else None,
        order_date=d,
        expected_delivery=body.expected_delivery,
        customer_po=body.customer_po,
        notes=body.notes,
    )
    so.id = uuid7()
    so.place_of_supply = _place_of_supply(db, ctx, acc, body.place_of_supply)
    rows = _price_doc(db, ctx, so, SalesOrderLine, "sales_order_id", body.lines, acc)
    db.add(so)
    db.flush()
    db.add_all(rows)
    db.flush()
    audit(
        db,
        ctx,
        "sales_order.created",
        "sales_order",
        so.id,
        after={"number": number, "grand_total": so.grand_total},
    )
    emit(db, ctx.tenant_id, "order.created", "sales_order", so.id, {"number": number})
    return so


@router.get("/orders")
def list_orders(
    params: PageParams = Depends(),
    status: str | None = None,
    account_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(require("sales.order.read")),
):
    q = (
        select(SalesOrder)
        .join(Account, Account.id == SalesOrder.account_id)
        .where(SalesOrder.tenant_id == ctx.tenant_id)
    )
    if status:
        q = q.where(SalesOrder.status.in_(status.split(",")))
    if account_id:
        q = q.where(SalesOrder.account_id == account_id)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(SalesOrder.number, Account.name, SalesOrder.customer_po),
        sortable={"order_date": SalesOrder.order_date, "grand_total": SalesOrder.grand_total},
        default_sort=SalesOrder.created_at.desc(),
    )
    page["data"] = [_so_out(ctx.db, x, with_lines=False) for x in page["data"]]
    return page


@router.post("/orders", status_code=201)
def create_order(
    body: OrderIn,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("sales.order.create")),
):
    return run_idempotent(
        ctx,
        idempotency_key,
        "sales.order.create",
        body.model_dump(mode="json"),
        lambda: _so_out(ctx.db, _create_order(ctx.db, ctx, body)),
    )


@router.get("/orders/{oid}")
def get_order(oid: uuid.UUID, ctx: Ctx = Depends(require("sales.order.read"))):
    return _so_out(ctx.db, get_or_404(ctx.db, SalesOrder, oid, ctx.tenant_id, "Sales order"))


def _stock_lines(db: Session, so: SalesOrder):
    from manima.modules.catalog.module import Item

    for ln in db.scalars(select(SalesOrderLine).where(SalesOrderLine.sales_order_id == so.id)):
        item = db.get(Item, ln.item_id) if ln.item_id else None
        if item and item.track_stock and item.type == "goods":
            yield ln, item


@router.post("/orders/{oid}:confirm")
def confirm_order(oid: uuid.UUID, ctx: Ctx = Depends(require("sales.order.update", "sales.order.create"))):
    """Confirm + reserve stock in one transaction (SCHEMA_DESIGN §6)."""
    db = ctx.db
    so = get_or_404(db, SalesOrder, oid, ctx.tenant_id, "Sales order", lock=True)
    if so.status != "draft":
        raise AppError(409, "INVALID_TRANSITION", f"Cannot confirm a {so.status} order.")
    if so.warehouse_id is None and any(True for _ in _stock_lines(db, so)):
        raise AppError(409, "WAREHOUSE_REQUIRED", "Select a warehouse to reserve stock.")
    for ln, item in _stock_lines(db, so):
        reserve(db, ctx.tenant_id, item.id, so.warehouse_id, ln.qty, "sales_order", so.id, ln.id)
    so.status = "confirmed"
    audit(
        db,
        ctx,
        "sales_order.confirmed",
        "sales_order",
        so.id,
        before={"status": "draft"},
        after={"status": "confirmed"},
    )
    emit(db, ctx.tenant_id, "order.confirmed", "sales_order", so.id, {"number": so.number})
    db.commit()
    return _so_out(db, so)


@router.post("/orders/{oid}:deliver")
def deliver_order(oid: uuid.UUID, ctx: Ctx = Depends(require("sales.order.update"))):
    """Dispatch: ledger rows, on_hand and reserved decrease, reservations fulfilled."""
    db = ctx.db
    so = get_or_404(db, SalesOrder, oid, ctx.tenant_id, "Sales order", lock=True)
    if so.status != "confirmed":
        raise AppError(409, "INVALID_TRANSITION", f"Cannot deliver a {so.status} order.")
    for ln, item in _stock_lines(db, so):
        move_stock(
            db,
            ctx.tenant_id,
            item.id,
            so.warehouse_id,
            -ln.qty,
            "sale",
            ref_type="sales_order",
            ref_id=so.id,
            ref_number=so.number,
            release_reserved=ln.qty,
            unit_cost=item.purchase_price,
            actor=ctx.user.id,
        )
        ln.delivered_qty = ln.qty
    release_reservations(db, ctx.tenant_id, "sales_order", so.id, status="fulfilled")
    so.status, so.delivered_at = "delivered", datetime.now(UTC)
    audit(
        db,
        ctx,
        "sales_order.delivered",
        "sales_order",
        so.id,
        before={"status": "confirmed"},
        after={"status": "delivered"},
    )
    emit(db, ctx.tenant_id, "order.delivered", "sales_order", so.id, {"number": so.number})
    db.commit()
    return _so_out(db, so)


@router.post("/orders/{oid}:cancel")
def cancel_order(oid: uuid.UUID, ctx: Ctx = Depends(require("sales.order.cancel"))):
    db = ctx.db
    so = get_or_404(db, SalesOrder, oid, ctx.tenant_id, "Sales order", lock=True)
    if so.status not in ("draft", "confirmed") or so.invoice_id:
        raise AppError(409, "INVALID_TRANSITION", "Only undelivered, uninvoiced orders can be cancelled.")
    release_reservations(db, ctx.tenant_id, "sales_order", so.id)
    before = so.status
    so.status = "cancelled"
    audit(
        db,
        ctx,
        "sales_order.cancelled",
        "sales_order",
        so.id,
        before={"status": before},
        after={"status": "cancelled"},
    )
    db.commit()
    return _so_out(db, so)
