"""Procurement: vendors, purchase orders (approve, send, receive goods into stock)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import CheckConstraint, Date, DateTime, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from manima.core.audit import audit, emit, snapshot
from manima.core.idempotency import run_idempotent
from manima.core.models import TenantSettings
from manima.core.routes_tenant import notify_members_with
from manima.core.security import Ctx, require
from manima.modules.catalog.module import Item
from manima.modules.compliance_gst.domain import STATES, validate_gstin
from manima.modules.compliance_gst.models import DocTotalsMixin, TaxLineMixin
from manima.modules.compliance_gst.service import next_number
from manima.modules.documents import LineInput, build, line_dicts, resolve_lines
from manima.modules.inventory.module import Warehouse, default_warehouse, move_stock
from manima.shared.crud import apply_patch, get_or_404, ref_or_422
from manima.shared.db import Base, Qty, TenantMixin, tenant_args, tfk, uuid7
from manima.shared.http import AppError, PageParams, paginate
from manima.shared.money import ZERO, r3
from manima.shared.schemas import Entity


class Vendor(TenantMixin, Base):
    __tablename__ = "vendors"
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(20))
    contact_person: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[dict] = mapped_column(JSONB, default=dict)
    state_code: Mapped[str | None] = mapped_column(String(2))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        CheckConstraint("gstin ~ '^[0-9]{2}[A-Z0-9]{13}$' or gstin is null", name="gstin_format")
    )


PO_STATUSES = ("draft", "pending_approval", "approved", "sent", "partially_received", "received", "cancelled")


class PurchaseOrder(TenantMixin, DocTotalsMixin, Base):
    __tablename__ = "purchase_orders"
    number: Mapped[str] = mapped_column(String(30))
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        tfk("vendor_id", "vendors"),
        tfk("warehouse_id", "warehouses"),
        CheckConstraint(f"status in {PO_STATUSES}", name="status"),
    )


class PurchaseOrderLine(TenantMixin, TaxLineMixin, Base):
    __tablename__ = "purchase_order_lines"
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    received_qty: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    __table_args__ = tenant_args(
        tfk("purchase_order_id", "purchase_orders", "CASCADE"),
        tfk("item_id", "items"),
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("received_qty >= 0 and received_qty <= qty", name="received_within_qty"),
    )


router = APIRouter(prefix="/api/v1/procurement", tags=["procurement"])


# =============================================================== vendors
class VendorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    gstin: str | None = None
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    contact_person: str | None = Field(None, max_length=120)
    address: dict = {}
    state_code: str | None = None
    payment_terms_days: int = Field(30, ge=0, le=365)

    @field_validator("gstin")
    @classmethod
    def _g(cls, v):
        if not v:
            return None
        v = v.strip().upper()
        if err := validate_gstin(v):
            raise ValueError(err)
        return v

    @field_validator("state_code")
    @classmethod
    def _s(cls, v):
        if v and v not in STATES:
            raise ValueError("Unknown state code.")
        return v or None


class VendorPatch(VendorIn):
    name: str | None = Field(None, min_length=1, max_length=200)  # type: ignore[assignment]
    version: int | None = None


class VendorOut(Entity):
    name: str
    gstin: str | None
    email: str | None
    phone: str | None
    contact_person: str | None
    address: dict
    state_code: str | None
    payment_terms_days: int


@router.get("/vendors")
def list_vendors(params: PageParams = Depends(), ctx: Ctx = Depends(require("procurement.vendor.read"))):
    q = select(Vendor).where(Vendor.tenant_id == ctx.tenant_id, Vendor.deleted_at.is_(None))
    return paginate(
        ctx.db,
        q,
        params,
        search_cols=(Vendor.name, Vendor.gstin, Vendor.email),
        sortable={"name": Vendor.name},
        default_sort=Vendor.name.asc(),
        schema=VendorOut,
    )


@router.post("/vendors", response_model=VendorOut, status_code=201)
def create_vendor(body: VendorIn, ctx: Ctx = Depends(require("procurement.vendor.manage"))):
    v = Vendor(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    if v.gstin and not v.state_code:
        v.state_code = v.gstin[:2]
    ctx.db.add(v)
    ctx.db.flush()
    audit(ctx.db, ctx, "vendor.created", "vendor", v.id, after=snapshot(v))
    ctx.db.commit()
    return v


@router.patch("/vendors/{vid}", response_model=VendorOut)
def update_vendor(
    vid: uuid.UUID, body: VendorPatch, ctx: Ctx = Depends(require("procurement.vendor.manage"))
):
    v = get_or_404(ctx.db, Vendor, vid, ctx.tenant_id, "Vendor")
    before = snapshot(v)
    apply_patch(v, body)
    if v.gstin and not v.state_code:
        v.state_code = v.gstin[:2]
    audit(ctx.db, ctx, "vendor.updated", "vendor", v.id, before=before, after=snapshot(v))
    ctx.db.commit()
    return v


@router.delete("/vendors/{vid}")
def delete_vendor(vid: uuid.UUID, ctx: Ctx = Depends(require("procurement.vendor.manage"))):
    v = get_or_404(ctx.db, Vendor, vid, ctx.tenant_id, "Vendor")
    v.deleted_at = datetime.now(UTC)
    audit(ctx.db, ctx, "vendor.deleted", "vendor", v.id)
    ctx.db.commit()
    return {"ok": True}


# =============================================================== purchase orders
class POIn(BaseModel):
    vendor_id: uuid.UUID
    warehouse_id: uuid.UUID | None = None
    order_date: date | None = None
    expected_date: date | None = None
    notes: str | None = Field(None, max_length=4000)
    lines: list[LineInput] = Field(min_length=1, max_length=200)
    version: int | None = None


class POOut(Entity):
    number: str
    vendor_id: uuid.UUID
    warehouse_id: uuid.UUID | None
    status: str
    order_date: date
    expected_date: date | None
    notes: str | None
    place_of_supply: str | None
    subtotal: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    tax_total: Decimal
    round_off: Decimal
    grand_total: Decimal
    approved_at: datetime | None


def _po_out(db: Session, po: PurchaseOrder, with_lines: bool = True) -> dict:
    out = POOut.model_validate(po).model_dump()
    v = db.get(Vendor, po.vendor_id)
    out["vendor_name"] = v.name if v else None
    out["vendor_gstin"] = v.gstin if v else None
    if with_lines:
        lines = list(
            db.scalars(
                select(PurchaseOrderLine)
                .where(PurchaseOrderLine.purchase_order_id == po.id)
                .order_by(PurchaseOrderLine.line_no)
            )
        )
        out["lines"] = [
            {**d, "received_qty": ln.received_qty} for d, ln in zip(line_dicts(lines), lines, strict=True)
        ]
    return out


def _fill_po(db: Session, ctx: Ctx, po: PurchaseOrder, body: POIn) -> list:
    vendor = ref_or_422(db, Vendor, body.vendor_id, ctx.tenant_id, "vendor_id", "Vendor")
    if vendor is None:
        raise AppError(422, "INVALID_REFERENCE", "Vendor is required.")
    wh = (
        ref_or_422(db, Warehouse, body.warehouse_id, ctx.tenant_id, "warehouse_id", "Warehouse")
        if body.warehouse_id
        else default_warehouse(db, ctx.tenant_id)
    )
    s = db.get(TenantSettings, ctx.tenant_id)
    po.vendor_id, po.warehouse_id = vendor.id, wh.id if wh else None
    po.order_date = body.order_date or date.today()
    po.expected_date, po.notes = body.expected_date, body.notes
    po.place_of_supply = s.state_code if s else None  # goods delivered to us
    resolved = resolve_lines(db, ctx.tenant_id, body.lines, price_field="purchase_price")
    return build(
        po,
        PurchaseOrderLine,
        "purchase_order_id",
        resolved,
        supplier_state=vendor.state_code,
        place_of_supply=po.place_of_supply,
        scenario="b2b",
    )


@router.get("/purchase-orders")
def list_pos(
    params: PageParams = Depends(),
    status: str | None = None,
    vendor_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(require("procurement.po.read")),
):
    q = (
        select(PurchaseOrder)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(PurchaseOrder.tenant_id == ctx.tenant_id)
    )
    if status:
        q = q.where(PurchaseOrder.status.in_(status.split(",")))
    if vendor_id:
        q = q.where(PurchaseOrder.vendor_id == vendor_id)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(PurchaseOrder.number, Vendor.name),
        sortable={"order_date": PurchaseOrder.order_date, "grand_total": PurchaseOrder.grand_total},
        default_sort=PurchaseOrder.created_at.desc(),
    )
    page["data"] = [_po_out(ctx.db, p, False) for p in page["data"]]
    return page


@router.post("/purchase-orders", status_code=201)
def create_po(
    body: POIn,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("procurement.po.create")),
):
    def do():
        db = ctx.db
        po = PurchaseOrder(
            tenant_id=ctx.tenant_id, created_by=ctx.user.id, number="", order_date=date.today()
        )
        po.id = uuid7()
        rows = _fill_po(db, ctx, po, body)
        po.number, _ = next_number(db, ctx.tenant_id, "purchase_order", po.order_date)
        db.add(po)
        db.flush()
        db.add_all(rows)
        db.flush()
        audit(
            db,
            ctx,
            "purchase_order.created",
            "purchase_order",
            po.id,
            after={"number": po.number, "total": po.grand_total},
        )
        return _po_out(db, po)

    return run_idempotent(ctx, idempotency_key, "procurement.po.create", body.model_dump(mode="json"), do)


@router.get("/purchase-orders/{pid}")
def get_po(pid: uuid.UUID, ctx: Ctx = Depends(require("procurement.po.read"))):
    return _po_out(ctx.db, get_or_404(ctx.db, PurchaseOrder, pid, ctx.tenant_id, "Purchase order"))


@router.patch("/purchase-orders/{pid}")
def update_po(pid: uuid.UUID, body: POIn, ctx: Ctx = Depends(require("procurement.po.create"))):
    db = ctx.db
    po = get_or_404(db, PurchaseOrder, pid, ctx.tenant_id, "Purchase order", lock=True)
    if po.status != "draft":
        raise AppError(409, "INVALID_TRANSITION", "Only draft purchase orders can be edited.")
    if body.version is not None and body.version != po.version:
        raise AppError(409, "VERSION_CONFLICT", "This purchase order changed. Reload and retry.")
    db.execute(PurchaseOrderLine.__table__.delete().where(PurchaseOrderLine.purchase_order_id == po.id))
    db.add_all(_fill_po(db, ctx, po, body))
    po.version += 1
    audit(db, ctx, "purchase_order.updated", "purchase_order", po.id, after={"total": po.grand_total})
    db.commit()
    return _po_out(db, po)


_PO_FLOW = {
    "submit": (("draft",), "pending_approval", "procurement.po.create"),
    "approve": (("draft", "pending_approval"), "approved", "procurement.po.approve"),
    "reject": (("pending_approval",), "draft", "procurement.po.approve"),
    "send": (("approved",), "sent", "procurement.po.create"),
    "cancel": (("draft", "pending_approval", "approved", "sent"), "cancelled", "procurement.po.create"),
}


@router.post("/purchase-orders/{pid}:{action}")
def po_action(pid: uuid.UUID, action: str, ctx: Ctx = Depends(require("procurement.po.read"))):
    if action == "receive":
        raise AppError(405, "METHOD_NOT_ALLOWED", "Use POST /purchase-orders/{id}/receipts.")
    if action not in _PO_FLOW:
        raise AppError(404, "NOT_FOUND", "Unknown action.")
    allowed, to, perm = _PO_FLOW[action]
    ctx.check(perm)
    db = ctx.db
    po = get_or_404(db, PurchaseOrder, pid, ctx.tenant_id, "Purchase order", lock=True)
    if po.status not in allowed:
        raise AppError(
            409, "INVALID_TRANSITION", f"Cannot {action} a {po.status.replace('_', ' ')} purchase order."
        )
    before = po.status
    po.status = to
    if action == "approve":
        po.approved_by, po.approved_at = ctx.user.id, datetime.now(UTC)
    if action == "submit":
        notify_members_with(
            db,
            ctx.tenant_id,
            "procurement.po.approve",
            f"PO {po.number} awaits approval",
            None,
            f"/procurement/purchase-orders/{po.id}",
            exclude=ctx.user.id,
        )
    if action == "send":
        v = db.get(Vendor, po.vendor_id)
        emit(
            db,
            ctx.tenant_id,
            "message.requested",
            "purchase_order",
            po.id,
            {
                "channel": "email",
                "to": v.email if v else None,
                "template": "purchase_order",
                "number": po.number,
            },
        )
    audit(
        db,
        ctx,
        f"purchase_order.{action}",
        "purchase_order",
        po.id,
        before={"status": before},
        after={"status": to},
    )
    db.commit()
    return _po_out(db, po)


class ReceiptLine(BaseModel):
    line_id: uuid.UUID
    qty: Decimal = Field(gt=0)


class ReceiptIn(BaseModel):
    lines: list[ReceiptLine] = Field(min_length=1)
    note: str | None = Field(None, max_length=300)


@router.post("/purchase-orders/{pid}/receipts")
def receive_goods(
    pid: uuid.UUID,
    body: ReceiptIn,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("procurement.po.receive")),
):
    """Goods receipt: stock ledger 'receipt' rows + balances + PO line progress, one transaction."""

    def do():
        db = ctx.db
        po = get_or_404(db, PurchaseOrder, pid, ctx.tenant_id, "Purchase order", lock=True)
        if po.status not in ("approved", "sent", "partially_received"):
            raise AppError(409, "INVALID_TRANSITION", "Only approved/sent purchase orders can be received.")
        if po.warehouse_id is None:
            raise AppError(409, "WAREHOUSE_REQUIRED", "Set a receiving warehouse first.")
        grn, _ = next_number(db, ctx.tenant_id, "goods_receipt", date.today())
        lines = {
            ln.id: ln
            for ln in db.scalars(
                select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id)
            )
        }
        for i, rl in enumerate(body.lines):
            ln = lines.get(rl.line_id)
            if ln is None:
                raise AppError(
                    422,
                    "INVALID_REFERENCE",
                    "PO line not found.",
                    [{"field": f"lines.{i}.line_id", "issue": "not_found"}],
                )
            if ln.received_qty + rl.qty > ln.qty:
                raise AppError(
                    422,
                    "OVER_RECEIPT",
                    f"Line {ln.line_no}: cannot receive more than ordered ({ln.qty - ln.received_qty} pending).",
                )
            ln.received_qty = r3(ln.received_qty + rl.qty)
            item = db.get(Item, ln.item_id) if ln.item_id else None
            if item and item.track_stock and item.type == "goods":
                move_stock(
                    db,
                    ctx.tenant_id,
                    item.id,
                    po.warehouse_id,
                    rl.qty,
                    "receipt",
                    ref_type="purchase_order",
                    ref_id=po.id,
                    ref_number=f"{po.number} / {grn}",
                    unit_cost=ln.rate,
                    note=body.note,
                    actor=ctx.user.id,
                )
        before = po.status
        po.status = (
            "received" if all(ln.received_qty >= ln.qty for ln in lines.values()) else "partially_received"
        )
        audit(
            db,
            ctx,
            "purchase_order.received",
            "purchase_order",
            po.id,
            before={"status": before},
            after={"status": po.status, "grn": grn},
        )
        emit(db, ctx.tenant_id, "goods.received", "purchase_order", po.id, {"grn": grn})
        return {**_po_out(db, po), "grn": grn}

    return run_idempotent(
        ctx, idempotency_key, f"procurement.po.receive:{pid}", body.model_dump(mode="json"), do
    )
