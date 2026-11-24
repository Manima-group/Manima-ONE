"""Payments received, allocations to invoices, refunds (reversal)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import CheckConstraint, Date, DateTime, String, Text, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from manima.core.audit import audit, emit
from manima.core.idempotency import run_idempotent
from manima.core.security import Ctx, require
from manima.modules.compliance_gst.service import next_number
from manima.modules.crm.module import Account, get_account
from manima.shared.crud import get_or_404
from manima.shared.db import Base, Money, TenantMixin, tenant_args, tfk
from manima.shared.http import AppError, PageParams, paginate
from manima.shared.money import ZERO, r2
from manima.shared.schemas import Entity

METHODS = ("upi", "card", "netbanking", "cash", "bank_transfer", "cheque")


class Payment(TenantMixin, Base):
    __tablename__ = "payments"
    number: Mapped[str] = mapped_column(String(30))
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    method: Mapped[str] = mapped_column(String(20))
    gateway: Mapped[str] = mapped_column(String(20), default="manual")
    gateway_payment_id: Mapped[str | None] = mapped_column(String(80))
    reference: Mapped[str | None] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20), default="succeeded")
    received_on: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        tfk("account_id", "accounts"),
        UniqueConstraint("tenant_id", "gateway", "gateway_payment_id"),
        CheckConstraint(f"method in {METHODS}", name="method"),
        CheckConstraint(
            "status in ('initiated','succeeded','failed','refunded','partially_refunded')", name="status"
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
    )


class PaymentAllocation(TenantMixin, Base):
    __tablename__ = "payment_allocations"
    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        tfk("payment_id", "payments"),
        tfk("invoice_id", "invoices"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )


# =============================================================== public helpers
def allocated_to_invoice(db: Session, tenant_id, invoice_id) -> Decimal:
    return (
        db.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.tenant_id == tenant_id,
                PaymentAllocation.invoice_id == invoice_id,
                PaymentAllocation.reversed_at.is_(None),
            )
        )
        or ZERO
    )


def _allocated_from_payment(db: Session, payment: Payment) -> Decimal:
    return (
        db.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.payment_id == payment.id, PaymentAllocation.reversed_at.is_(None)
            )
        )
        or ZERO
    )


def allocations_for_invoice(db: Session, tenant_id, invoice_id) -> list[dict]:
    rows = db.execute(
        select(PaymentAllocation, Payment)
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(PaymentAllocation.tenant_id == tenant_id, PaymentAllocation.invoice_id == invoice_id)
        .order_by(Payment.received_on)
    ).all()
    return [
        {
            "payment_id": p.id,
            "number": p.number,
            "method": p.method,
            "received_on": p.received_on,
            "amount": a.amount,
            "reversed": a.reversed_at is not None,
        }
        for a, p in rows
    ]


router = APIRouter(prefix="/api/v1/billing", tags=["payments"])


class AllocationIn(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal = Field(gt=0)


class PaymentIn(BaseModel):
    account_id: uuid.UUID
    amount: Decimal = Field(gt=0, le=Decimal("9999999999"))
    method: str = Field(pattern="^(" + "|".join(METHODS) + ")$")
    reference: str | None = Field(None, max_length=80)
    received_on: date | None = None
    notes: str | None = Field(None, max_length=2000)
    allocations: list[AllocationIn] = []


class PaymentOut(Entity):
    number: str
    account_id: uuid.UUID
    method: str
    reference: str | None
    amount: Decimal
    status: str
    received_on: date
    notes: str | None
    refunded_at: datetime | None


def _pay_out(db: Session, p: Payment, detail: bool = False) -> dict:
    from manima.modules.invoicing.module import Invoice

    out = PaymentOut.model_validate(p).model_dump()
    acc = db.get(Account, p.account_id)
    out["account_name"] = acc.name if acc else None
    allocated = _allocated_from_payment(db, p)
    out["allocated"] = allocated
    out["unallocated"] = r2(p.amount - allocated) if p.status == "succeeded" else ZERO
    if detail:
        rows = db.execute(
            select(PaymentAllocation, Invoice.number)
            .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(PaymentAllocation.payment_id == p.id)
        ).all()
        out["allocations"] = [
            {
                "invoice_id": a.invoice_id,
                "invoice_number": n,
                "amount": a.amount,
                "reversed": a.reversed_at is not None,
            }
            for a, n in rows
        ]
    return out


def _allocate(db: Session, ctx: Ctx, payment: Payment, allocations: list[AllocationIn]) -> None:
    from manima.modules.invoicing.module import Invoice, refresh_payment_state

    available = payment.amount - _allocated_from_payment(db, payment)
    total = sum((a.amount for a in allocations), ZERO)
    if total > available:
        raise AppError(
            422,
            "ALLOCATION_EXCEEDS_PAYMENT",
            f"Allocations ({total}) exceed the unallocated amount ({available}).",
        )
    for i, a in enumerate(allocations):
        inv = db.get(Invoice, a.invoice_id, with_for_update=True)
        if inv is None or inv.tenant_id != ctx.tenant_id:
            raise AppError(
                422,
                "INVALID_REFERENCE",
                "Invoice not found.",
                [{"field": f"allocations.{i}.invoice_id", "issue": "not_found"}],
            )
        if inv.account_id != payment.account_id:
            raise AppError(422, "ACCOUNT_MISMATCH", f"Invoice {inv.number} belongs to another customer.")
        if inv.document_status != "issued":
            raise AppError(409, "INVALID_TRANSITION", "Payments can only be allocated to issued invoices.")
        paid = allocated_to_invoice(db, ctx.tenant_id, inv.id)
        if a.amount > inv.grand_total + inv.debit_total - inv.credit_total - paid:
            raise AppError(422, "ALLOCATION_EXCEEDS_DUE", f"Amount exceeds the balance due on {inv.number}.")
        db.add(
            PaymentAllocation(
                tenant_id=ctx.tenant_id,
                payment_id=payment.id,
                invoice_id=inv.id,
                amount=r2(a.amount),
                created_by=ctx.user.id,
            )
        )
        db.flush()
        refresh_payment_state(db, inv, paid + a.amount)


@router.get("/payments")
def list_payments(
    params: PageParams = Depends(),
    account_id: uuid.UUID | None = None,
    method: str | None = None,
    status: str | None = None,
    ctx: Ctx = Depends(require("payments.payment.read")),
):
    q = (
        select(Payment)
        .join(Account, Account.id == Payment.account_id)
        .where(Payment.tenant_id == ctx.tenant_id)
    )
    if account_id:
        q = q.where(Payment.account_id == account_id)
    if method:
        q = q.where(Payment.method == method)
    if status:
        q = q.where(Payment.status == status)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(Payment.number, Payment.reference, Account.name),
        sortable={"received_on": Payment.received_on, "amount": Payment.amount},
        default_sort=Payment.created_at.desc(),
    )
    page["data"] = [_pay_out(ctx.db, p) for p in page["data"]]
    return page


@router.post("/payments", status_code=201)
def record_payment(
    body: PaymentIn,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("payments.payment.create")),
):
    """Payment + allocations + invoice payment_status in one transaction."""

    def do():
        db = ctx.db
        acc = get_account(db, ctx.tenant_id, body.account_id)
        d = body.received_on or date.today()
        number, _ = next_number(db, ctx.tenant_id, "payment", d)
        p = Payment(
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            number=number,
            account_id=acc.id,
            method=body.method,
            reference=body.reference,
            amount=r2(body.amount),
            received_on=d,
            notes=body.notes,
        )
        db.add(p)
        db.flush()
        _allocate(db, ctx, p, body.allocations)
        audit(db, ctx, "payment.recorded", "payment", p.id, after={"number": number, "amount": p.amount})
        emit(
            db,
            ctx.tenant_id,
            "payment.received",
            "payment",
            p.id,
            {"amount": str(p.amount), "account_id": str(acc.id)},
        )
        return _pay_out(db, p, True)

    return run_idempotent(ctx, idempotency_key, "payments.payment.create", body.model_dump(mode="json"), do)


@router.get("/payments/{pid}")
def get_payment(pid: uuid.UUID, ctx: Ctx = Depends(require("payments.payment.read"))):
    return _pay_out(ctx.db, get_or_404(ctx.db, Payment, pid, ctx.tenant_id, "Payment"), True)


class AllocateIn(BaseModel):
    allocations: list[AllocationIn] = Field(min_length=1)


@router.post("/payments/{pid}:allocate")
def allocate_payment(
    pid: uuid.UUID, body: AllocateIn, ctx: Ctx = Depends(require("payments.payment.create"))
):
    db = ctx.db
    p = get_or_404(db, Payment, pid, ctx.tenant_id, "Payment", lock=True)
    if p.status != "succeeded":
        raise AppError(409, "INVALID_TRANSITION", "Only successful payments can be allocated.")
    _allocate(db, ctx, p, body.allocations)
    audit(
        db,
        ctx,
        "payment.allocated",
        "payment",
        p.id,
        after={"allocations": [a.model_dump(mode="json") for a in body.allocations]},
    )
    db.commit()
    return _pay_out(db, p, True)


class RefundIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/payments/{pid}:refund")
def refund_payment(pid: uuid.UUID, body: RefundIn, ctx: Ctx = Depends(require("payments.payment.refund"))):
    """Full reversal: allocations reversed, invoices' payment state recomputed."""
    from manima.modules.invoicing.module import Invoice, refresh_payment_state

    db = ctx.db
    p = get_or_404(db, Payment, pid, ctx.tenant_id, "Payment", lock=True)
    if p.status != "succeeded":
        raise AppError(409, "INVALID_TRANSITION", f"A {p.status} payment cannot be refunded.")
    now = datetime.now(UTC)
    for a in db.scalars(
        select(PaymentAllocation).where(
            PaymentAllocation.payment_id == p.id, PaymentAllocation.reversed_at.is_(None)
        )
    ):
        a.reversed_at = now
        db.flush()
        inv = db.get(Invoice, a.invoice_id, with_for_update=True)
        refresh_payment_state(db, inv, allocated_to_invoice(db, ctx.tenant_id, inv.id))
    p.status, p.refunded_at = "refunded", now
    audit(db, ctx, "payment.refunded", "payment", p.id, after={"reason": body.reason})
    emit(db, ctx.tenant_id, "payment.refunded", "payment", p.id, {"amount": str(p.amount)})
    db.commit()
    return _pay_out(db, p, True)
