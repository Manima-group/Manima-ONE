"""Product & service catalog: items with HSN/SAC and GST rate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, CheckConstraint, DateTime, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from manima.core.audit import audit, snapshot
from manima.core.security import Ctx, require
from manima.modules.compliance_gst.domain import VALID_RATES
from manima.shared.crud import apply_patch, get_or_404
from manima.shared.db import Base, Money, Qty, Rate, TenantMixin, tenant_args
from manima.shared.http import AppError, PageParams, paginate
from manima.shared.money import ZERO
from manima.shared.schemas import Entity

UNITS = (
    "nos",
    "pcs",
    "kg",
    "g",
    "ltr",
    "ml",
    "m",
    "cm",
    "box",
    "set",
    "pack",
    "hrs",
    "day",
    "month",
    "job",
    "sqft",
)


class Item(TenantMixin, Base):
    __tablename__ = "items"
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(10), default="goods")
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80))
    hsn_sac: Mapped[str | None] = mapped_column(String(8))
    unit: Mapped[str] = mapped_column(String(10), default="nos")
    gst_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("18"))
    cess_rate: Mapped[Decimal] = mapped_column(Rate, default=ZERO)
    price: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    purchase_price: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    track_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    reorder_level: Mapped[Decimal] = mapped_column(Qty, default=ZERO)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "sku"),
        CheckConstraint("type in ('goods','service')", name="type"),
        CheckConstraint("price >= 0 and purchase_price >= 0", name="price_non_negative"),
    )


class ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    type: str = Field("goods", pattern="^(goods|service)$")
    description: str | None = Field(None, max_length=4000)
    category: str | None = Field(None, max_length=80)
    hsn_sac: str | None = Field(None, pattern=r"^[0-9]{4,8}$")
    unit: str = "nos"
    gst_rate: Decimal = Decimal("18")
    cess_rate: Decimal = Field(ZERO, ge=0, le=300)
    price: Decimal = Field(ZERO, ge=0)
    purchase_price: Decimal = Field(ZERO, ge=0)
    track_stock: bool = True
    reorder_level: Decimal = Field(ZERO, ge=0)
    active: bool = True

    @field_validator("gst_rate")
    @classmethod
    def _rate(cls, v: Decimal) -> Decimal:
        if v not in VALID_RATES:
            raise ValueError("Not a valid GST rate.")
        return v

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        if v not in UNITS:
            raise ValueError(f"Unit must be one of {', '.join(UNITS)}")
        return v


class ItemPatch(ItemIn):
    sku: str | None = Field(None, min_length=1, max_length=40)  # type: ignore[assignment]
    name: str | None = Field(None, min_length=1, max_length=200)  # type: ignore[assignment]
    version: int | None = None


class ItemOut(Entity):
    sku: str
    name: str
    type: str
    description: str | None
    category: str | None
    hsn_sac: str | None
    unit: str
    gst_rate: Decimal
    cess_rate: Decimal
    price: Decimal
    purchase_price: Decimal
    track_stock: bool
    reorder_level: Decimal
    active: bool


router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


@router.get("/units")
def units():
    return list(UNITS)


@router.get("/items")
def list_items(
    params: PageParams = Depends(),
    type: str | None = None,
    active: bool | None = None,
    category: str | None = None,
    ctx: Ctx = Depends(require("catalog.item.read")),
):
    q = select(Item).where(Item.tenant_id == ctx.tenant_id, Item.deleted_at.is_(None))
    if type:
        q = q.where(Item.type == type)
    if active is not None:
        q = q.where(Item.active.is_(active))
    if category:
        q = q.where(Item.category == category)
    return paginate(
        ctx.db,
        q,
        params,
        search_cols=(Item.name, Item.sku, Item.hsn_sac, Item.category),
        sortable={"name": Item.name, "sku": Item.sku, "price": Item.price, "created_at": Item.created_at},
        default_sort=Item.name.asc(),
        schema=ItemOut,
    )


@router.get("/categories")
def categories(ctx: Ctx = Depends(require("catalog.item.read"))):
    return [
        c
        for c in ctx.db.scalars(
            select(Item.category)
            .distinct()
            .where(Item.tenant_id == ctx.tenant_id, Item.category.is_not(None), Item.deleted_at.is_(None))
            .order_by(Item.category)
        )
    ]


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(body: ItemIn, ctx: Ctx = Depends(require("catalog.item.create"))):
    db = ctx.db
    if db.scalar(
        select(Item.id).where(Item.tenant_id == ctx.tenant_id, func.lower(Item.sku) == body.sku.lower())
    ):
        raise AppError(
            409, "DUPLICATE_SKU", "An item with this SKU exists.", [{"field": "sku", "issue": "duplicate"}]
        )
    item = Item(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    if item.type == "service":
        item.track_stock = False
    db.add(item)
    db.flush()
    audit(db, ctx, "item.created", "item", item.id, after=snapshot(item))
    db.commit()
    return item


@router.get("/items/{iid}", response_model=ItemOut)
def get_item(iid: uuid.UUID, ctx: Ctx = Depends(require("catalog.item.read"))):
    return get_or_404(ctx.db, Item, iid, ctx.tenant_id, "Item")


@router.patch("/items/{iid}", response_model=ItemOut)
def update_item(iid: uuid.UUID, body: ItemPatch, ctx: Ctx = Depends(require("catalog.item.update"))):
    db = ctx.db
    item = get_or_404(db, Item, iid, ctx.tenant_id, "Item")
    if (
        body.sku
        and body.sku.lower() != item.sku.lower()
        and db.scalar(
            select(Item.id).where(Item.tenant_id == ctx.tenant_id, func.lower(Item.sku) == body.sku.lower())
        )
    ):
        raise AppError(
            409, "DUPLICATE_SKU", "An item with this SKU exists.", [{"field": "sku", "issue": "duplicate"}]
        )
    before = snapshot(item)
    apply_patch(item, body)
    audit(db, ctx, "item.updated", "item", item.id, before=before, after=snapshot(item))
    db.commit()
    return item


@router.delete("/items/{iid}")
def delete_item(iid: uuid.UUID, ctx: Ctx = Depends(require("catalog.item.delete"))):
    item = get_or_404(ctx.db, Item, iid, ctx.tenant_id, "Item")
    item.deleted_at, item.active = datetime.now(UTC), False
    audit(ctx.db, ctx, "item.deleted", "item", item.id)
    ctx.db.commit()
    return {"ok": True}
