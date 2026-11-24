"""Shared line/tax builder for GST documents (quotations, orders, invoices, notes, POs)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from manima.modules.catalog.module import Item
from manima.modules.compliance_gst.domain import VALID_RATES, LineIn, compute_document
from manima.shared.http import AppError
from manima.shared.money import ZERO


class LineInput(BaseModel):
    item_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=500)
    qty: Decimal = Field(gt=0, le=Decimal("999999999"))
    rate: Decimal | None = Field(None, ge=0)
    discount_pct: Decimal = Field(ZERO, ge=0, le=100)
    gst_rate: Decimal | None = None
    unit: str | None = None
    hsn_sac: str | None = None

    @field_validator("gst_rate")
    @classmethod
    def _rate(cls, v):
        if v is not None and v not in VALID_RATES:
            raise ValueError("Not a valid GST rate.")
        return v


LINE_FIELDS = (
    "line_no",
    "item_id",
    "description",
    "hsn_sac",
    "qty",
    "unit",
    "rate",
    "discount_pct",
    "discount",
    "taxable_value",
    "gst_rate",
    "cgst_rate",
    "cgst",
    "sgst_rate",
    "sgst",
    "igst_rate",
    "igst",
    "cess_rate",
    "cess",
    "total",
)
TOTAL_FIELDS = (
    "subtotal",
    "discount_total",
    "taxable_total",
    "cgst_total",
    "sgst_total",
    "igst_total",
    "cess_total",
    "tax_total",
    "round_off",
    "grand_total",
)


def resolve_lines(
    db: Session, tenant_id: uuid.UUID, lines: list[LineInput], *, price_field: str = "price"
) -> list[dict]:
    """Fill defaults from the catalog; validate item ownership (composite FK also blocks cross-tenant)."""
    ids = {ln.item_id for ln in lines if ln.item_id}
    items = (
        {
            i.id: i
            for i in db.scalars(
                select(Item).where(Item.tenant_id == tenant_id, Item.id.in_(ids), Item.deleted_at.is_(None))
            )
        }
        if ids
        else {}
    )
    out = []
    for i, ln in enumerate(lines):
        item = items.get(ln.item_id) if ln.item_id else None
        if ln.item_id and item is None:
            raise AppError(
                422,
                "INVALID_REFERENCE",
                "Item not found.",
                [{"field": f"lines.{i}.item_id", "issue": "not_found"}],
            )
        desc = ln.description or (item.name if item else None)
        if not desc:
            raise AppError(
                422,
                "VALIDATION_FAILED",
                "Line description is required.",
                [{"field": f"lines.{i}.description", "issue": "required"}],
            )
        out.append(
            {
                "line_no": i + 1,
                "item_id": item.id if item else None,
                "description": desc,
                "hsn_sac": ln.hsn_sac or (item.hsn_sac if item else None),
                "qty": ln.qty,
                "unit": ln.unit or (item.unit if item else "nos"),
                "rate": ln.rate if ln.rate is not None else (getattr(item, price_field) if item else ZERO),
                "discount_pct": ln.discount_pct,
                "gst_rate": ln.gst_rate
                if ln.gst_rate is not None
                else (item.gst_rate if item else Decimal("18")),
                "cess_rate": item.cess_rate if item else ZERO,
                "_track_stock": bool(item and item.track_stock and item.type == "goods"),
            }
        )
    return out


def build(
    doc,
    line_model,
    fk: str,
    resolved: list[dict],
    *,
    supplier_state: str | None,
    place_of_supply: str | None,
    scenario: str = "b2b",
    composition: bool = False,
) -> list:
    """Compute taxes, set totals on ``doc`` and return new line ORM objects (caller adds them)."""
    totals = compute_document(
        [LineIn(r["qty"], r["rate"], r["discount_pct"], r["gst_rate"], r["cess_rate"]) for r in resolved],
        supplier_state=supplier_state,
        place_of_supply=place_of_supply,
        scenario=scenario,
        composition=composition,
    )
    for f in TOTAL_FIELDS:
        setattr(doc, f, getattr(totals, f))
    rows = []
    for r, lt in zip(resolved, totals.lines, strict=True):
        data = {k: v for k, v in r.items() if not k.startswith("_")}
        data.update(
            taxable_value=lt.taxable_value,
            discount=lt.discount,
            cgst_rate=lt.cgst_rate,
            cgst=lt.cgst,
            sgst_rate=lt.sgst_rate,
            sgst=lt.sgst,
            igst_rate=lt.igst_rate,
            igst=lt.igst,
            cess=lt.cess,
            total=lt.total,
        )
        if composition or scenario in ("export_lut", "sez_lut"):
            data["gst_rate"] = r["gst_rate"] if not composition else ZERO
        rows.append(line_model(tenant_id=doc.tenant_id, **{fk: doc.id}, **data))
    return rows


def line_dicts(lines) -> list[dict]:
    return [{f: getattr(ln, f) for f in ("id", *LINE_FIELDS)} for ln in lines]


def lines_as_input(lines) -> list[LineInput]:
    return [
        LineInput(
            item_id=ln.item_id,
            description=ln.description,
            qty=ln.qty,
            rate=ln.rate,
            discount_pct=ln.discount_pct,
            gst_rate=ln.gst_rate,
            unit=ln.unit,
            hsn_sac=ln.hsn_sac,
        )
        for ln in lines
    ]
