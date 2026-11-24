"""Inventory: warehouses, append-only stock ledger, balances, reservations, adjustments, transfers."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from manima.core.audit import audit, emit, snapshot
from manima.core.idempotency import run_idempotent
from manima.core.models import TenantSettings
from manima.core.provisioning import on_enable
from manima.core.security import Ctx, require
from manima.modules.catalog.module import Item
from manima.modules.compliance_gst.service import next_number
from manima.shared.crud import apply_patch, get_or_404, ref_or_422
from manima.shared.db import Base, Money, Qty, TenantMixin, tenant_args, tfk
from manima.shared.http import AppError, PageParams, paginate
from manima.shared.money import ZERO, r3
from manima.shared.schemas import Entity


class Warehouse(TenantMixin, Base):
    __tablename__ = "warehouses"
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(20))
    address: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "code"))


REASONS = ("opening", "receipt", "sale", "transfer_out", "transfer_in", "adjustment", "return")


class StockLedger(TenantMixin, Base):
    """Append-only (no UPDATE/DELETE grant for the runtime role)."""

    __tablename__ = "stock_ledger"
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    qty_change: Mapped[Decimal] = mapped_column(Qty)
    balance_after: Mapped[Decimal] = mapped_column(Qty)
    unit_cost: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    reason: Mapped[str] = mapped_column(String(20))
    ref_type: Mapped[str | None] = mapped_column(String(30))
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ref_number: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(String(300))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = tenant_args(
        tfk("item_id", "items"),
        tfk("warehouse_id", "warehouses"),
        CheckConstraint(f"reason in {REASONS}", name="reason"),
        CheckConstraint("qty_change <> 0", name="qty_nonzero"),
    )


class StockBalance(TenantMixin, Base):
    __tablename__ = "stock_balances"
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    on_hand: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    reserved: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "item_id", "warehouse_id"),
        tfk("item_id", "items"),
        tfk("warehouse_id", "warehouses"),
        CheckConstraint("reserved >= 0", name="reserved_non_negative"),
    )


class Reservation(TenantMixin, Base):
    __tablename__ = "reservations"
    ref_type: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    ref_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    qty: Mapped[Decimal] = mapped_column(Qty)
    status: Mapped[str] = mapped_column(String(12), default="active")
    __table_args__ = tenant_args(
        tfk("item_id", "items"),
        tfk("warehouse_id", "warehouses"),
        CheckConstraint("status in ('active','fulfilled','released','expired')", name="status"),
        CheckConstraint("qty > 0", name="qty_positive"),
    )


class StockAdjustment(TenantMixin, Base):
    __tablename__ = "stock_adjustments"
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    qty_change: Mapped[Decimal] = mapped_column(Qty)
    reason: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = tenant_args(tfk("item_id", "items"), tfk("warehouse_id", "warehouses"))


class StockTransfer(TenantMixin, Base):
    __tablename__ = "stock_transfers"
    number: Mapped[str] = mapped_column(String(30))
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    transfer_date: Mapped[date] = mapped_column(Date)
    lines: Mapped[list] = mapped_column(JSONB, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = tenant_args(
        tfk("from_warehouse_id", "warehouses"),
        tfk("to_warehouse_id", "warehouses"),
        CheckConstraint("status in ('draft','in_transit','received','cancelled')", name="status"),
        CheckConstraint("from_warehouse_id <> to_warehouse_id", name="distinct_warehouses"),
    )


@on_enable("inventory")
def _seed_warehouse(db: Session, tenant_id: uuid.UUID) -> None:
    if not db.scalar(select(Warehouse.id).where(Warehouse.tenant_id == tenant_id)):
        db.add(Warehouse(tenant_id=tenant_id, name="Main warehouse", code="MAIN", is_default=True))


# =============================================================== public service (used by sales / procurement)
def default_warehouse(db: Session, tenant_id: uuid.UUID) -> Warehouse | None:
    return db.scalar(
        select(Warehouse)
        .where(Warehouse.tenant_id == tenant_id, Warehouse.active.is_(True))
        .order_by(Warehouse.is_default.desc(), Warehouse.created_at)
    )


def _balance(db: Session, tenant_id, item_id, warehouse_id) -> StockBalance:
    q = (
        select(StockBalance)
        .where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.item_id == item_id,
            StockBalance.warehouse_id == warehouse_id,
        )
        .with_for_update()
    )
    bal = db.scalar(q)
    if bal is None:
        db.add(
            StockBalance(
                tenant_id=tenant_id, item_id=item_id, warehouse_id=warehouse_id, on_hand=ZERO, reserved=ZERO
            )
        )
        db.flush()
        bal = db.scalar(q)
    return bal


def _allow_negative(db: Session, tenant_id) -> bool:
    s = db.get(TenantSettings, tenant_id)
    return bool(s and s.allow_negative_stock)


def move_stock(
    db: Session,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    qty_change: Decimal,
    reason: str,
    *,
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
    ref_number: str | None = None,
    unit_cost: Decimal = ZERO,
    note: str | None = None,
    release_reserved: Decimal = ZERO,
    actor: uuid.UUID | None = None,
) -> StockLedger:
    """Write one ledger row and update the balance in the caller's transaction (row-locked)."""
    qty_change = r3(qty_change)
    if qty_change == 0:
        raise AppError(422, "INVALID_QUANTITY", "Quantity cannot be zero.")
    bal = _balance(db, tenant_id, item_id, warehouse_id)
    new_on_hand = bal.on_hand + qty_change
    new_reserved = bal.reserved - release_reserved
    if new_reserved < 0:
        new_reserved = ZERO
    if qty_change < 0 and new_on_hand < 0 and not _allow_negative(db, tenant_id):
        item = db.get(Item, item_id)
        raise AppError(
            409,
            "INSUFFICIENT_STOCK",
            f"Not enough stock for {item.name if item else 'item'}: available {bal.on_hand}, needed {-qty_change}.",
            item_id=str(item_id),
        )
    bal.on_hand, bal.reserved = new_on_hand, new_reserved
    row = StockLedger(
        tenant_id=tenant_id,
        item_id=item_id,
        warehouse_id=warehouse_id,
        qty_change=qty_change,
        balance_after=new_on_hand,
        unit_cost=unit_cost,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        ref_number=ref_number,
        note=note,
        created_by=actor,
    )
    db.add(row)
    emit(
        db,
        tenant_id,
        "stock.changed",
        "item",
        item_id,
        {
            "warehouse_id": str(warehouse_id),
            "qty_change": str(qty_change),
            "on_hand": str(new_on_hand),
            "reason": reason,
        },
    )
    return row


def reserve(
    db: Session, tenant_id, item_id, warehouse_id, qty: Decimal, ref_type: str, ref_id, ref_line_id=None
) -> None:
    bal = _balance(db, tenant_id, item_id, warehouse_id)
    available = bal.on_hand - bal.reserved
    if qty > available and not _allow_negative(db, tenant_id):
        item = db.get(Item, item_id)
        raise AppError(
            409,
            "INSUFFICIENT_STOCK",
            f"Only {available} of {item.name if item else 'item'} available to reserve.",
            item_id=str(item_id),
        )
    bal.reserved += qty
    db.add(
        Reservation(
            tenant_id=tenant_id,
            ref_type=ref_type,
            ref_id=ref_id,
            ref_line_id=ref_line_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            qty=qty,
        )
    )


def release_reservations(db: Session, tenant_id, ref_type: str, ref_id, status: str = "released") -> None:
    for r in db.scalars(
        select(Reservation).where(
            Reservation.tenant_id == tenant_id,
            Reservation.ref_type == ref_type,
            Reservation.ref_id == ref_id,
            Reservation.status == "active",
        )
    ):
        if status == "released":
            bal = _balance(db, tenant_id, r.item_id, r.warehouse_id)
            bal.reserved = max(ZERO, bal.reserved - r.qty)
        r.status = status


def on_hand(db: Session, tenant_id, item_id) -> Decimal:
    return (
        db.scalar(
            select(func.coalesce(func.sum(StockBalance.on_hand), 0)).where(
                StockBalance.tenant_id == tenant_id, StockBalance.item_id == item_id
            )
        )
        or ZERO
    )


# =============================================================== routes
router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


class WarehouseIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    address: dict = {}
    is_default: bool = False
    active: bool = True


class WarehousePatch(WarehouseIn):
    name: str | None = Field(None, min_length=1, max_length=100)  # type: ignore[assignment]
    code: str | None = Field(None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")  # type: ignore[assignment]
    version: int | None = None


class WarehouseOut(Entity):
    name: str
    code: str
    address: dict
    is_default: bool
    active: bool


@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(
    ctx: Ctx = Depends(require("inventory.stock.read", "sales.order.read", "procurement.po.read")),
):
    return ctx.db.scalars(
        select(Warehouse)
        .where(Warehouse.tenant_id == ctx.tenant_id)
        .order_by(Warehouse.is_default.desc(), Warehouse.name)
    ).all()


def _single_default(db, tenant_id, keep_id):
    for w in db.scalars(select(Warehouse).where(Warehouse.tenant_id == tenant_id, Warehouse.id != keep_id)):
        w.is_default = False


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
def create_warehouse(body: WarehouseIn, ctx: Ctx = Depends(require("inventory.warehouse.manage"))):
    db = ctx.db
    if db.scalar(
        select(Warehouse.id).where(Warehouse.tenant_id == ctx.tenant_id, Warehouse.code == body.code.upper())
    ):
        raise AppError(
            409, "DUPLICATE_CODE", "Warehouse code exists.", [{"field": "code", "issue": "duplicate"}]
        )
    w = Warehouse(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    w.code = w.code.upper()
    db.add(w)
    db.flush()
    if w.is_default:
        _single_default(db, ctx.tenant_id, w.id)
    audit(db, ctx, "warehouse.created", "warehouse", w.id, after=snapshot(w))
    db.commit()
    return w


@router.patch("/warehouses/{wid}", response_model=WarehouseOut)
def update_warehouse(
    wid: uuid.UUID, body: WarehousePatch, ctx: Ctx = Depends(require("inventory.warehouse.manage"))
):
    w = get_or_404(ctx.db, Warehouse, wid, ctx.tenant_id, "Warehouse")
    before = snapshot(w)
    apply_patch(w, body)
    w.code = w.code.upper()
    if w.is_default:
        _single_default(ctx.db, ctx.tenant_id, w.id)
    audit(ctx.db, ctx, "warehouse.updated", "warehouse", w.id, before=before, after=snapshot(w))
    ctx.db.commit()
    return w


@router.get("/stock")
def stock_levels(
    params: PageParams = Depends(),
    warehouse_id: uuid.UUID | None = None,
    low_only: bool = False,
    ctx: Ctx = Depends(require("inventory.stock.read")),
):
    db = ctx.db
    on_hand_col = func.coalesce(func.sum(StockBalance.on_hand), 0)
    reserved_col = func.coalesce(func.sum(StockBalance.reserved), 0)
    join_cond = (StockBalance.item_id == Item.id) & (StockBalance.tenant_id == Item.tenant_id)
    if warehouse_id:
        join_cond = join_cond & (StockBalance.warehouse_id == warehouse_id)
    q = (
        select(
            Item.id,
            Item.sku,
            Item.name,
            Item.unit,
            Item.reorder_level,
            Item.purchase_price,
            on_hand_col.label("on_hand"),
            reserved_col.label("reserved"),
        )
        .outerjoin(StockBalance, join_cond)
        .where(Item.tenant_id == ctx.tenant_id, Item.deleted_at.is_(None), Item.track_stock.is_(True))
        .group_by(Item.id)
    )
    if params.q:
        q = q.where(Item.name.ilike(f"%{params.q}%") | Item.sku.ilike(f"%{params.q}%"))
    if low_only:
        q = q.having(on_hand_col <= Item.reorder_level)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.order_by(Item.name).limit(params.limit).offset(params.offset)).all()
    data = [
        {
            "item_id": r.id,
            "sku": r.sku,
            "name": r.name,
            "unit": r.unit,
            "on_hand": r.on_hand,
            "reserved": r.reserved,
            "available": r.on_hand - r.reserved,
            "reorder_level": r.reorder_level,
            "value": (r.on_hand * r.purchase_price).quantize(Decimal("0.01")),
            "low": r.on_hand <= r.reorder_level,
        }
        for r in rows
    ]
    return {"data": data, "total": total, "limit": params.limit, "offset": params.offset}


@router.get("/stock/{item_id}")
def item_stock(item_id: uuid.UUID, ctx: Ctx = Depends(require("inventory.stock.read"))):
    db = ctx.db
    item = get_or_404(db, Item, item_id, ctx.tenant_id, "Item")
    rows = db.execute(
        select(StockBalance, Warehouse.name)
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .where(StockBalance.item_id == item.id)
    ).all()
    return {
        "item_id": item.id,
        "name": item.name,
        "sku": item.sku,
        "warehouses": [
            {
                "warehouse_id": b.warehouse_id,
                "warehouse": n,
                "on_hand": b.on_hand,
                "reserved": b.reserved,
                "available": b.on_hand - b.reserved,
            }
            for b, n in rows
        ],
    }


class LedgerOut(Entity):
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty_change: Decimal
    balance_after: Decimal
    reason: str
    ref_type: str | None
    ref_id: uuid.UUID | None
    ref_number: str | None
    note: str | None
    occurred_at: datetime


@router.get("/ledger")
def ledger(
    params: PageParams = Depends(),
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    reason: str | None = None,
    ctx: Ctx = Depends(require("inventory.stock.read")),
):
    q = select(StockLedger).where(StockLedger.tenant_id == ctx.tenant_id)
    if item_id:
        q = q.where(StockLedger.item_id == item_id)
    if warehouse_id:
        q = q.where(StockLedger.warehouse_id == warehouse_id)
    if reason:
        q = q.where(StockLedger.reason == reason)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(StockLedger.ref_number, StockLedger.note),
        default_sort=StockLedger.occurred_at.desc(),
        schema=LedgerOut,
    )
    items = dict(
        ctx.db.execute(select(Item.id, Item.name).where(Item.id.in_({r.item_id for r in page["data"]}))).all()
    )
    whs = dict(
        ctx.db.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.tenant_id == ctx.tenant_id)).all()
    )
    page["data"] = [
        {**r.model_dump(), "item_name": items.get(r.item_id), "warehouse_name": whs.get(r.warehouse_id)}
        for r in page["data"]
    ]
    return page


class AdjustmentIn(BaseModel):
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty_change: Decimal
    reason: str = Field(pattern="^(opening|count_correction|damage|expiry|theft|other)$")
    note: str | None = Field(None, max_length=300)


@router.post("/adjustments", status_code=201)
def adjust(
    body: AdjustmentIn,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("inventory.adjustment.create")),
):
    def do():
        db = ctx.db
        item = ref_or_422(db, Item, body.item_id, ctx.tenant_id, "item_id", "Item")
        if not item.track_stock:
            raise AppError(422, "NOT_STOCKED", "This item does not track stock.")
        ref_or_422(db, Warehouse, body.warehouse_id, ctx.tenant_id, "warehouse_id", "Warehouse")
        adj = StockAdjustment(
            tenant_id=ctx.tenant_id, created_by=ctx.user.id, approved_by=ctx.user.id, **body.model_dump()
        )
        db.add(adj)
        db.flush()
        led = move_stock(
            db,
            ctx.tenant_id,
            body.item_id,
            body.warehouse_id,
            body.qty_change,
            "opening" if body.reason == "opening" else "adjustment",
            ref_type="stock_adjustment",
            ref_id=adj.id,
            note=body.note or body.reason,
            unit_cost=item.purchase_price,
            actor=ctx.user.id,
        )
        audit(db, ctx, "stock.adjusted", "stock_adjustment", adj.id, after=snapshot(adj))
        return {"id": adj.id, "balance_after": led.balance_after}

    return run_idempotent(ctx, idempotency_key, "inventory.adjust", body.model_dump(mode="json"), do)


class TransferLine(BaseModel):
    item_id: uuid.UUID
    qty: Decimal = Field(gt=0)


class TransferIn(BaseModel):
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    transfer_date: date | None = None
    lines: list[TransferLine] = Field(min_length=1)
    note: str | None = Field(None, max_length=1000)


class TransferOut(Entity):
    number: str
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    status: str
    transfer_date: date
    lines: list
    note: str | None


@router.get("/transfers")
def list_transfers(
    params: PageParams = Depends(),
    status: str | None = None,
    ctx: Ctx = Depends(require("inventory.stock.read")),
):
    q = select(StockTransfer).where(StockTransfer.tenant_id == ctx.tenant_id)
    if status:
        q = q.where(StockTransfer.status == status)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(StockTransfer.number,),
        default_sort=StockTransfer.created_at.desc(),
        schema=TransferOut,
    )
    whs = dict(
        ctx.db.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.tenant_id == ctx.tenant_id)).all()
    )
    page["data"] = [
        {**t.model_dump(), "from_name": whs.get(t.from_warehouse_id), "to_name": whs.get(t.to_warehouse_id)}
        for t in page["data"]
    ]
    return page


@router.post("/transfers", response_model=TransferOut, status_code=201)
def create_transfer(
    body: TransferIn,
    idempotency_key: str | None = Header(None),
    ctx: Ctx = Depends(require("inventory.transfer.manage")),
):
    def do():
        db = ctx.db
        if body.from_warehouse_id == body.to_warehouse_id:
            raise AppError(422, "SAME_WAREHOUSE", "Choose two different warehouses.")
        ref_or_422(db, Warehouse, body.from_warehouse_id, ctx.tenant_id, "from_warehouse_id", "Warehouse")
        ref_or_422(db, Warehouse, body.to_warehouse_id, ctx.tenant_id, "to_warehouse_id", "Warehouse")
        lines = []
        for i, ln in enumerate(body.lines):
            item = ref_or_422(db, Item, ln.item_id, ctx.tenant_id, f"lines.{i}.item_id", "Item")
            lines.append({"item_id": str(item.id), "name": item.name, "qty": str(r3(ln.qty))})
        d = body.transfer_date or date.today()
        number, _ = next_number(db, ctx.tenant_id, "stock_transfer", d)
        t = StockTransfer(
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            number=number,
            transfer_date=d,
            lines=lines,
            from_warehouse_id=body.from_warehouse_id,
            to_warehouse_id=body.to_warehouse_id,
            note=body.note,
        )
        db.add(t)
        db.flush()
        audit(db, ctx, "transfer.created", "stock_transfer", t.id, after=snapshot(t))
        return TransferOut.model_validate(t)

    return run_idempotent(ctx, idempotency_key, "inventory.transfer.create", body.model_dump(mode="json"), do)


@router.post("/transfers/{tid}:{action}", response_model=TransferOut)
def transfer_action(tid: uuid.UUID, action: str, ctx: Ctx = Depends(require("inventory.transfer.manage"))):
    db = ctx.db
    t = get_or_404(db, StockTransfer, tid, ctx.tenant_id, "Transfer", lock=True)
    allowed = {
        "dispatch": ("draft", "in_transit"),
        "receive": ("in_transit", "received"),
        "cancel": ("draft", "cancelled"),
    }
    if action not in allowed:
        raise AppError(404, "NOT_FOUND", "Unknown action.")
    frm, to = allowed[action]
    if t.status != frm:
        raise AppError(409, "INVALID_TRANSITION", f"Transfer is {t.status}; cannot {action}.")
    for ln in t.lines:
        qty = Decimal(ln["qty"])
        if action == "dispatch":
            move_stock(
                db,
                ctx.tenant_id,
                uuid.UUID(ln["item_id"]),
                t.from_warehouse_id,
                -qty,
                "transfer_out",
                ref_type="stock_transfer",
                ref_id=t.id,
                ref_number=t.number,
                actor=ctx.user.id,
            )
        elif action == "receive":
            move_stock(
                db,
                ctx.tenant_id,
                uuid.UUID(ln["item_id"]),
                t.to_warehouse_id,
                qty,
                "transfer_in",
                ref_type="stock_transfer",
                ref_id=t.id,
                ref_number=t.number,
                actor=ctx.user.id,
            )
    t.status = to
    audit(db, ctx, f"transfer.{action}", "stock_transfer", t.id, before={"status": frm}, after={"status": to})
    db.commit()
    return t


_ = UTC
