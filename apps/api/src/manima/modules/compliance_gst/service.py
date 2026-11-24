"""GST registrations, gapless number series (row-locked) and GST report queries (public surface)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from manima.core.models import TenantSettings
from manima.modules.compliance_gst.domain import financial_year
from manima.modules.compliance_gst.models import GstRegistration, NumberSeries
from manima.shared.http import AppError

DEFAULT_PREFIX = {
    "tax_invoice": "INV/{fy}/",
    "bill_of_supply": "BOS/{fy}/",
    "credit_note": "CN/{fy}/",
    "debit_note": "DN/{fy}/",
    "quotation": "QT/{fy}/",
    "sales_order": "SO/{fy}/",
    "purchase_order": "PO/{fy}/",
    "payment": "RCP/{fy}/",
    "stock_transfer": "TRF/{fy}/",
    "goods_receipt": "GRN/{fy}/",
}
GST_DOCS = ("tax_invoice", "bill_of_supply", "credit_note", "debit_note")


def fy_start_month(db: Session, tenant_id: uuid.UUID) -> int:
    s = db.get(TenantSettings, tenant_id)
    return s.fiscal_year_start_month if s else 4


def next_number(
    db: Session, tenant_id: uuid.UUID, doc_type: str, on: date, gst_registration_id: uuid.UUID | None = None
) -> tuple[str, uuid.UUID]:
    """Allocate the next number inside the caller's transaction (SELECT ... FOR UPDATE ⇒ gapless)."""
    fy = financial_year(on, fy_start_month(db, tenant_id))
    reg_id = gst_registration_id if doc_type in GST_DOCS else None
    q = (
        select(NumberSeries)
        .where(
            NumberSeries.tenant_id == tenant_id,
            NumberSeries.doc_type == doc_type,
            NumberSeries.financial_year == fy,
            NumberSeries.gst_registration_id.is_(None)
            if reg_id is None
            else NumberSeries.gst_registration_id == reg_id,
        )
        .with_for_update()
    )
    series = db.scalar(q)
    if series is None:
        series = NumberSeries(
            tenant_id=tenant_id,
            gst_registration_id=reg_id,
            doc_type=doc_type,
            financial_year=fy,
            prefix=DEFAULT_PREFIX.get(doc_type, "DOC/{fy}/").format(fy=fy),
            next_value=1,
        )
        db.add(series)
        db.flush()
        series = db.scalar(q)
    number = f"{series.prefix}{series.next_value:0{series.padding}d}"
    if doc_type in GST_DOCS and len(number) > 16:
        raise AppError(
            422, "NUMBER_TOO_LONG", "GST document numbers must be at most 16 characters; shorten the prefix."
        )
    series.next_value += 1
    return number, series.id


def default_registration(db: Session, tenant_id: uuid.UUID) -> GstRegistration | None:
    return db.scalar(
        select(GstRegistration)
        .where(GstRegistration.tenant_id == tenant_id)
        .order_by(GstRegistration.is_default.desc(), GstRegistration.created_at)
    )


def get_registration(db: Session, tenant_id: uuid.UUID, reg_id: uuid.UUID | None) -> GstRegistration | None:
    if reg_id is None:
        return default_registration(db, tenant_id)
    r = db.get(GstRegistration, reg_id)
    if r is None or r.tenant_id != tenant_id:
        raise AppError(
            422,
            "INVALID_REFERENCE",
            "GST registration not found.",
            [{"field": "gst_registration_id", "issue": "not_found"}],
        )
    return r


def supplier_state(db: Session, tenant_id: uuid.UUID, reg: GstRegistration | None) -> str | None:
    if reg:
        return reg.state_code
    s = db.get(TenantSettings, tenant_id)
    return s.state_code if s else None
