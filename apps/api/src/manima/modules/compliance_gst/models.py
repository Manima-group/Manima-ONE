from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from manima.shared.db import Base, Money, Qty, Rate, TenantMixin, tenant_args, tfk
from manima.shared.money import ZERO


class GstRegistration(TenantMixin, Base):
    __tablename__ = "gst_registrations"
    gstin: Mapped[str] = mapped_column(String(15))
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str | None] = mapped_column(String(200))
    state_code: Mapped[str] = mapped_column(String(2))
    registration_type: Mapped[str] = mapped_column(String(20), default="regular")
    address: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    e_invoice_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "gstin"),
        CheckConstraint(
            "registration_type in ('regular','composition','sez_unit')", name="registration_type"
        ),
        CheckConstraint("gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'", name="gstin_format"),
    )


class NumberSeries(TenantMixin, Base):
    __tablename__ = "number_series"
    gst_registration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    doc_type: Mapped[str] = mapped_column(String(30))
    financial_year: Mapped[str] = mapped_column(String(7))
    prefix: Mapped[str] = mapped_column(String(12))
    padding: Mapped[int] = mapped_column(Integer, default=5)
    next_value: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = tenant_args(
        UniqueConstraint(
            "tenant_id",
            "gst_registration_id",
            "doc_type",
            "financial_year",
            postgresql_nulls_not_distinct=True,
        ),
        tfk("gst_registration_id", "gst_registrations"),
        CheckConstraint("next_value > 0", name="next_value_positive"),
    )


class HsnSac(Base):
    """Global reference table (not tenant scoped)."""

    __tablename__ = "hsn_sac_codes"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    description: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(3))
    default_rate: Mapped[Decimal] = mapped_column(Rate)


class TaxLineMixin:
    """Tax columns shared by quotation, order, invoice, note and PO lines."""

    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(String(500))
    hsn_sac: Mapped[str | None] = mapped_column(String(8))
    qty: Mapped[Decimal] = mapped_column(Qty)
    unit: Mapped[str] = mapped_column(String(10), default="nos")
    rate: Mapped[Decimal] = mapped_column(Money)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=ZERO)
    discount: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    taxable_value: Mapped[Decimal] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Rate, default=ZERO)
    cgst_rate: Mapped[Decimal] = mapped_column(Rate, default=ZERO)
    cgst: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    sgst_rate: Mapped[Decimal] = mapped_column(Rate, default=ZERO)
    sgst: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    igst_rate: Mapped[Decimal] = mapped_column(Rate, default=ZERO)
    igst: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    cess_rate: Mapped[Decimal] = mapped_column(Rate, default=ZERO)
    cess: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    total: Mapped[Decimal] = mapped_column(Money)


class DocTotalsMixin:
    place_of_supply: Mapped[str | None] = mapped_column(String(2))
    subtotal: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    discount_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    taxable_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    cgst_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    sgst_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    igst_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    cess_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    round_off: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    grand_total: Mapped[Decimal] = mapped_column(Money, default=ZERO)


_ = Qty
