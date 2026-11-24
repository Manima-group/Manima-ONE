"""CRM: leads, accounts (customers), contacts, pipelines, opportunities, activities & tasks."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from manima.core.audit import audit, emit, notify, snapshot
from manima.core.models import TenantMembership
from manima.core.provisioning import on_enable
from manima.core.security import Ctx, require
from manima.modules.compliance_gst.domain import STATES, validate_gstin
from manima.shared.crud import apply_patch, get_or_404, ref_or_422
from manima.shared.db import SCHEMA, Base, Money, TenantMixin, tenant_args, tfk
from manima.shared.http import AppError, PageParams, paginate
from manima.shared.money import ZERO
from manima.shared.schemas import Entity


# =============================================================== models
class Account(TenantMixin, Base):
    __tablename__ = "accounts"
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="customer")
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(80))
    billing_address: Mapped[dict] = mapped_column(JSONB, default=dict)
    shipping_address: Mapped[dict] = mapped_column(JSONB, default=dict)
    state_code: Mapped[str | None] = mapped_column(String(2))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    credit_limit: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.platform_users.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        CheckConstraint("gstin ~ '^[0-9]{2}[A-Z0-9]{13}$' or gstin is null", name="gstin_format"),
        CheckConstraint("type in ('customer','prospect','partner')", name="type"),
    )


class Contact(TenantMixin, Base):
    __tablename__ = "contacts"
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(20))
    designation: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(tfk("account_id", "accounts"))


LEAD_STATUSES = ("new", "contacted", "qualified", "converted", "lost")
LEAD_SOURCES = ("form", "manual", "import", "whatsapp", "email", "referral", "website", "event")


class Lead(TenantMixin, Base):
    __tablename__ = "leads"
    name: Mapped[str] = mapped_column(String(120))
    company: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254), index=True)
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="new")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.platform_users.id"), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    estimated_value: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    notes: Mapped[str | None] = mapped_column(Text)
    lost_reason: Mapped[str | None] = mapped_column(String(300))
    converted_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        tfk("converted_account_id", "accounts"),
        CheckConstraint(f"status in {LEAD_STATUSES}", name="status"),
        CheckConstraint("score between 0 and 100", name="score"),
    )


class Pipeline(TenantMixin, Base):
    __tablename__ = "pipelines"
    name: Mapped[str] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = tenant_args()


class PipelineStage(TenantMixin, Base):
    __tablename__ = "pipeline_stages"
    pipeline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    probability: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(10), default="open")
    __table_args__ = tenant_args(
        tfk("pipeline_id", "pipelines", "CASCADE"),
        CheckConstraint("outcome in ('open','won','lost')", name="outcome"),
    )


class Opportunity(TenantMixin, Base):
    __tablename__ = "opportunities"
    name: Mapped[str] = mapped_column(String(200))
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    pipeline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    value: Mapped[Decimal] = mapped_column(Money, default=ZERO)
    expected_close: Mapped[date | None] = mapped_column(Date)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.platform_users.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="open")
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        tfk("account_id", "accounts"),
        tfk("contact_id", "contacts"),
        tfk("pipeline_id", "pipelines"),
        tfk("stage_id", "pipeline_stages"),
        tfk("lead_id", "leads"),
        CheckConstraint("value >= 0", name="value_non_negative"),
    )


ACTIVITY_TYPES = ("call", "note", "meeting", "task", "email", "message")
RELATED = ("lead", "account", "contact", "opportunity", "quotation", "sales_order", "invoice")


class Activity(TenantMixin, Base):
    __tablename__ = "activities"
    type: Mapped[str] = mapped_column(String(10))
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    related_type: Mapped[str | None] = mapped_column(String(20))
    related_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.platform_users.id"), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_args(
        CheckConstraint(f"type in {ACTIVITY_TYPES}", name="type"),
        CheckConstraint("priority in ('low','normal','high')", name="priority"),
    )


# =============================================================== hooks
DEFAULT_STAGES = [
    ("Qualification", 10, "open"),
    ("Needs analysis", 30, "open"),
    ("Proposal", 60, "open"),
    ("Negotiation", 80, "open"),
    ("Won", 100, "won"),
    ("Lost", 0, "lost"),
]


@on_enable("crm")
def _seed_pipeline(db: Session, tenant_id: uuid.UUID) -> None:
    if db.scalar(select(Pipeline.id).where(Pipeline.tenant_id == tenant_id)):
        return
    p = Pipeline(tenant_id=tenant_id, name="Sales pipeline", is_default=True)
    db.add(p)
    db.flush()
    for i, (n, prob, outcome) in enumerate(DEFAULT_STAGES):
        db.add(
            PipelineStage(
                tenant_id=tenant_id, pipeline_id=p.id, name=n, position=i, probability=prob, outcome=outcome
            )
        )


# =============================================================== public helpers (used by other modules)
def get_account(
    db: Session, tenant_id: uuid.UUID, account_id: uuid.UUID | None, field: str = "account_id"
) -> Account:
    acc = ref_or_422(db, Account, account_id, tenant_id, field, "Customer")
    if acc is None:
        raise AppError(
            422, "INVALID_REFERENCE", "Customer is required.", [{"field": field, "issue": "required"}]
        )
    return acc


def _ensure_member(db: Session, ctx: Ctx, user_id: uuid.UUID | None, field: str) -> None:
    if user_id is None:
        return
    ok = db.scalar(
        select(TenantMembership.id).where(
            TenantMembership.tenant_id == ctx.tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    )
    if not ok:
        raise AppError(
            422,
            "INVALID_REFERENCE",
            "Assignee is not an employee of this company.",
            [{"field": field, "issue": "not_found"}],
        )


def _own_guard(ctx: Ctx, base: str, owner_id: uuid.UUID | None, what: str) -> None:
    if ctx.own_only(base) and owner_id != ctx.user.id:
        raise AppError(404, "NOT_FOUND", f"{what} not found.")


router = APIRouter(prefix="/api/v1/crm", tags=["crm"])


# =============================================================== accounts & contacts
class AddressIn(BaseModel):
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    country: str | None = "IN"


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field("customer", pattern="^(customer|prospect|partner)$")
    gstin: str | None = None
    pan: str | None = Field(None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    website: str | None = Field(None, max_length=200)
    industry: str | None = Field(None, max_length=80)
    billing_address: dict = {}
    shipping_address: dict = {}
    state_code: str | None = None
    payment_terms_days: int = Field(30, ge=0, le=365)
    credit_limit: Decimal = Field(ZERO, ge=0)
    owner_id: uuid.UUID | None = None
    notes: str | None = Field(None, max_length=4000)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v):
        if not v:
            return None
        v = v.strip().upper()
        err = validate_gstin(v)
        if err:
            raise ValueError(err)
        return v

    @field_validator("state_code")
    @classmethod
    def _state(cls, v):
        if v and v not in STATES:
            raise ValueError("Unknown state code.")
        return v or None


class AccountPatch(AccountIn):
    name: str | None = Field(None, min_length=1, max_length=200)  # type: ignore[assignment]
    version: int | None = None


class AccountOut(Entity):
    name: str
    type: str
    gstin: str | None
    pan: str | None
    email: str | None
    phone: str | None
    website: str | None
    industry: str | None
    billing_address: dict
    shipping_address: dict
    state_code: str | None
    payment_terms_days: int
    credit_limit: Decimal
    owner_id: uuid.UUID | None
    notes: str | None


def _normalise_account(acc: Account) -> None:
    if acc.gstin and not acc.state_code:
        acc.state_code = acc.gstin[:2]
    if acc.gstin and not acc.pan:
        acc.pan = acc.gstin[2:12]


@router.get("/accounts")
def list_accounts(
    params: PageParams = Depends(),
    type: str | None = None,
    owner_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(require("crm.account.read")),
):
    q = select(Account).where(Account.tenant_id == ctx.tenant_id, Account.deleted_at.is_(None))
    if type:
        q = q.where(Account.type == type)
    if owner_id:
        q = q.where(Account.owner_id == owner_id)
    return paginate(
        ctx.db,
        q,
        params,
        search_cols=(Account.name, Account.gstin, Account.email, Account.phone),
        sortable={"name": Account.name, "created_at": Account.created_at},
        default_sort=Account.name.asc(),
        schema=AccountOut,
    )


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(body: AccountIn, ctx: Ctx = Depends(require("crm.account.create"))):
    db = ctx.db
    _ensure_member(db, ctx, body.owner_id, "owner_id")
    if body.gstin and db.scalar(
        select(Account.id).where(
            Account.tenant_id == ctx.tenant_id, Account.gstin == body.gstin, Account.deleted_at.is_(None)
        )
    ):
        raise AppError(
            409,
            "DUPLICATE_GSTIN",
            "A customer with this GSTIN exists.",
            [{"field": "gstin", "issue": "duplicate"}],
        )
    acc = Account(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    acc.owner_id = acc.owner_id or ctx.user.id
    _normalise_account(acc)
    db.add(acc)
    db.flush()
    audit(db, ctx, "account.created", "account", acc.id, after=snapshot(acc))
    emit(db, ctx.tenant_id, "account.created", "account", acc.id, {"name": acc.name})
    db.commit()
    return acc


@router.get("/accounts/{aid}")
def get_account_detail(aid: uuid.UUID, ctx: Ctx = Depends(require("crm.account.read"))):
    db = ctx.db
    acc = get_or_404(db, Account, aid, ctx.tenant_id, "Customer")
    contacts = db.scalars(
        select(Contact)
        .where(Contact.account_id == acc.id, Contact.deleted_at.is_(None))
        .order_by(Contact.is_primary.desc(), Contact.name)
    ).all()
    out = AccountOut.model_validate(acc).model_dump()
    out["contacts"] = [ContactOut.model_validate(c).model_dump() for c in contacts]
    return out


@router.patch("/accounts/{aid}", response_model=AccountOut)
def update_account(aid: uuid.UUID, body: AccountPatch, ctx: Ctx = Depends(require("crm.account.update"))):
    db = ctx.db
    acc = get_or_404(db, Account, aid, ctx.tenant_id, "Customer")
    _ensure_member(db, ctx, body.owner_id, "owner_id")
    before = snapshot(acc)
    apply_patch(acc, body)
    _normalise_account(acc)
    audit(db, ctx, "account.updated", "account", acc.id, before=before, after=snapshot(acc))
    db.commit()
    return acc


@router.delete("/accounts/{aid}")
def delete_account(aid: uuid.UUID, ctx: Ctx = Depends(require("crm.account.delete"))):
    acc = get_or_404(ctx.db, Account, aid, ctx.tenant_id, "Customer")
    acc.deleted_at = datetime.now(UTC)
    audit(ctx.db, ctx, "account.deleted", "account", acc.id)
    ctx.db.commit()
    return {"ok": True}


class ContactIn(BaseModel):
    account_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    designation: str | None = Field(None, max_length=100)
    is_primary: bool = False


class ContactPatch(ContactIn):
    name: str | None = Field(None, min_length=1, max_length=120)  # type: ignore[assignment]
    version: int | None = None


class ContactOut(Entity):
    account_id: uuid.UUID | None
    name: str
    email: str | None
    phone: str | None
    designation: str | None
    is_primary: bool


@router.get("/contacts")
def list_contacts(
    params: PageParams = Depends(),
    account_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(require("crm.account.read")),
):
    q = select(Contact).where(Contact.tenant_id == ctx.tenant_id, Contact.deleted_at.is_(None))
    if account_id:
        q = q.where(Contact.account_id == account_id)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(Contact.name, Contact.email, Contact.phone),
        sortable={"name": Contact.name},
        default_sort=Contact.name.asc(),
        schema=ContactOut,
    )
    names = dict(
        ctx.db.execute(
            select(Account.id, Account.name).where(
                Account.id.in_([c.account_id for c in page["data"] if c.account_id])
            )
        ).all()
    )
    page["data"] = [{**c.model_dump(), "account_name": names.get(c.account_id)} for c in page["data"]]
    return page


@router.post("/contacts", response_model=ContactOut, status_code=201)
def create_contact(body: ContactIn, ctx: Ctx = Depends(require("crm.account.create"))):
    ref_or_422(ctx.db, Account, body.account_id, ctx.tenant_id, "account_id", "Customer")
    c = Contact(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx.db, ctx, "contact.created", "contact", c.id, after=snapshot(c))
    ctx.db.commit()
    return c


@router.patch("/contacts/{cid}", response_model=ContactOut)
def update_contact(cid: uuid.UUID, body: ContactPatch, ctx: Ctx = Depends(require("crm.account.update"))):
    c = get_or_404(ctx.db, Contact, cid, ctx.tenant_id, "Contact")
    if "account_id" in body.model_fields_set:
        ref_or_422(ctx.db, Account, body.account_id, ctx.tenant_id, "account_id", "Customer")
    before = snapshot(c)
    apply_patch(c, body)
    audit(ctx.db, ctx, "contact.updated", "contact", c.id, before=before, after=snapshot(c))
    ctx.db.commit()
    return c


@router.delete("/contacts/{cid}")
def delete_contact(cid: uuid.UUID, ctx: Ctx = Depends(require("crm.account.delete"))):
    c = get_or_404(ctx.db, Contact, cid, ctx.tenant_id, "Contact")
    c.deleted_at = datetime.now(UTC)
    audit(ctx.db, ctx, "contact.deleted", "contact", c.id)
    ctx.db.commit()
    return {"ok": True}


# =============================================================== leads
class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    company: str | None = Field(None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    source: str = "manual"
    status: str = "new"
    owner_id: uuid.UUID | None = None
    score: int = Field(0, ge=0, le=100)
    estimated_value: Decimal = Field(ZERO, ge=0)
    notes: str | None = Field(None, max_length=4000)
    lost_reason: str | None = Field(None, max_length=300)

    @field_validator("source")
    @classmethod
    def _src(cls, v):
        if v not in LEAD_SOURCES:
            raise ValueError("Unknown source.")
        return v

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v not in LEAD_STATUSES or v == "converted":
            raise ValueError("Invalid status (use convert to convert a lead).")
        return v


class LeadPatch(LeadIn):
    name: str | None = Field(None, min_length=1, max_length=120)  # type: ignore[assignment]
    version: int | None = None


class LeadOut(Entity):
    name: str
    company: str | None
    email: str | None
    phone: str | None
    source: str
    status: str
    owner_id: uuid.UUID | None
    score: int
    estimated_value: Decimal
    notes: str | None
    lost_reason: str | None
    converted_account_id: uuid.UUID | None
    converted_at: datetime | None


def _duplicates(db: Session, tenant_id, email, phone, exclude=None) -> list[dict]:
    conds = []
    if email:
        conds.append(func.lower(Lead.email) == email.lower())
    if phone:
        conds.append(Lead.phone == phone)
    if not conds:
        return []
    q = select(Lead).where(Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None), or_(*conds))
    if exclude:
        q = q.where(Lead.id != exclude)
    return [{"id": d.id, "name": d.name, "status": d.status} for d in db.scalars(q.limit(5))]


@router.get("/leads")
def list_leads(
    params: PageParams = Depends(),
    status: str | None = None,
    source: str | None = None,
    owner_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(require("crm.lead.read_all", "crm.lead.read_own")),
):
    q = select(Lead).where(Lead.tenant_id == ctx.tenant_id, Lead.deleted_at.is_(None))
    if ctx.own_only("crm.lead"):
        q = q.where(Lead.owner_id == ctx.user.id)
    if status:
        q = q.where(Lead.status.in_(status.split(",")))
    if source:
        q = q.where(Lead.source == source)
    if owner_id:
        q = q.where(Lead.owner_id == owner_id)
    return paginate(
        ctx.db,
        q,
        params,
        search_cols=(Lead.name, Lead.company, Lead.email, Lead.phone),
        sortable={
            "name": Lead.name,
            "created_at": Lead.created_at,
            "score": Lead.score,
            "estimated_value": Lead.estimated_value,
        },
        default_sort=Lead.created_at.desc(),
        schema=LeadOut,
    )


@router.post("/leads", status_code=201)
def create_lead(body: LeadIn, ctx: Ctx = Depends(require("crm.lead.create"))):
    db = ctx.db
    owner = body.owner_id or ctx.user.id
    if ctx.own_only("crm.lead"):
        owner = ctx.user.id
    _ensure_member(db, ctx, owner, "owner_id")
    dups = _duplicates(db, ctx.tenant_id, body.email, body.phone)
    lead = Lead(
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        **body.model_dump(exclude={"owner_id"}),
        owner_id=owner,
    )
    db.add(lead)
    db.flush()
    audit(db, ctx, "lead.created", "lead", lead.id, after=snapshot(lead))
    emit(db, ctx.tenant_id, "lead.created", "lead", lead.id, {"owner_id": str(owner), "name": lead.name})
    if owner != ctx.user.id:
        notify(
            db,
            ctx.tenant_id,
            owner,
            f"New lead assigned: {lead.name}",
            lead.company,
            f"/crm/leads/{lead.id}",
            "lead",
        )
    db.commit()
    return {**LeadOut.model_validate(lead).model_dump(), "duplicates": dups}


@router.get("/leads/{lid}")
def get_lead(lid: uuid.UUID, ctx: Ctx = Depends(require("crm.lead.read_all", "crm.lead.read_own"))):
    lead = get_or_404(ctx.db, Lead, lid, ctx.tenant_id, "Lead")
    _own_guard(ctx, "crm.lead", lead.owner_id, "Lead")
    return {
        **LeadOut.model_validate(lead).model_dump(),
        "duplicates": _duplicates(ctx.db, ctx.tenant_id, lead.email, lead.phone, exclude=lead.id),
    }


class ConvertIn(BaseModel):
    account_name: str | None = None
    existing_account_id: uuid.UUID | None = None
    create_opportunity: bool = True
    opportunity_name: str | None = None
    opportunity_value: Decimal | None = Field(None, ge=0)


@router.post("/leads/{lid}:convert")
def convert_lead(lid: uuid.UUID, body: ConvertIn, ctx: Ctx = Depends(require("crm.lead.convert"))):
    """Convert to account + contact (+ opportunity) in one transaction."""
    db = ctx.db
    lead = get_or_404(db, Lead, lid, ctx.tenant_id, "Lead", lock=True)
    _own_guard(ctx, "crm.lead", lead.owner_id, "Lead")
    if lead.status == "converted":
        raise AppError(409, "INVALID_TRANSITION", "Lead is already converted.")
    if body.existing_account_id:
        acc = get_account(db, ctx.tenant_id, body.existing_account_id, "existing_account_id")
    else:
        acc = Account(
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            name=body.account_name or lead.company or lead.name,
            email=lead.email,
            phone=lead.phone,
            owner_id=lead.owner_id or ctx.user.id,
            type="customer",
        )
        db.add(acc)
        db.flush()
    contact = Contact(
        tenant_id=ctx.tenant_id,
        account_id=acc.id,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        is_primary=True,
        created_by=ctx.user.id,
    )
    db.add(contact)
    db.flush()
    opp = None
    if body.create_opportunity:
        pipeline = db.scalar(
            select(Pipeline).where(Pipeline.tenant_id == ctx.tenant_id).order_by(Pipeline.is_default.desc())
        )
        if pipeline is None:
            _seed_pipeline(db, ctx.tenant_id)
            db.flush()
            pipeline = db.scalar(select(Pipeline).where(Pipeline.tenant_id == ctx.tenant_id))
        stage = db.scalar(
            select(PipelineStage)
            .where(PipelineStage.pipeline_id == pipeline.id)
            .order_by(PipelineStage.position)
        )
        opp = Opportunity(
            tenant_id=ctx.tenant_id,
            name=body.opportunity_name or f"{acc.name} - {lead.name}",
            account_id=acc.id,
            contact_id=contact.id,
            pipeline_id=pipeline.id,
            stage_id=stage.id,
            value=body.opportunity_value if body.opportunity_value is not None else lead.estimated_value,
            owner_id=lead.owner_id or ctx.user.id,
            lead_id=lead.id,
            created_by=ctx.user.id,
        )
        db.add(opp)
        db.flush()
    before = {"status": lead.status}
    lead.status, lead.converted_account_id, lead.converted_at = "converted", acc.id, datetime.now(UTC)
    audit(
        db,
        ctx,
        "lead.converted",
        "lead",
        lead.id,
        before=before,
        after={"account_id": acc.id, "contact_id": contact.id, "opportunity_id": opp.id if opp else None},
    )
    emit(db, ctx.tenant_id, "lead.converted", "lead", lead.id, {"account_id": str(acc.id)})
    db.commit()
    return {"account_id": acc.id, "contact_id": contact.id, "opportunity_id": opp.id if opp else None}


@router.patch("/leads/{lid}")
def update_lead(lid: uuid.UUID, body: LeadPatch, ctx: Ctx = Depends(require("crm.lead.update"))):
    db = ctx.db
    lead = get_or_404(db, Lead, lid, ctx.tenant_id, "Lead")
    _own_guard(ctx, "crm.lead", lead.owner_id, "Lead")
    if lead.status == "converted":
        raise AppError(409, "INVALID_TRANSITION", "Converted leads cannot be edited.")
    if "owner_id" in body.model_fields_set:
        if ctx.own_only("crm.lead") and body.owner_id != ctx.user.id:
            raise AppError(403, "PERMISSION_DENIED", "You can only own your leads.")
        _ensure_member(db, ctx, body.owner_id, "owner_id")
    if body.status == "lost" and not (body.lost_reason or lead.lost_reason):
        raise AppError(
            422,
            "LOST_REASON_REQUIRED",
            "Give a reason for losing the lead.",
            [{"field": "lost_reason", "issue": "required"}],
        )
    before = snapshot(lead)
    old_owner = lead.owner_id
    apply_patch(lead, body)
    if lead.owner_id and lead.owner_id != old_owner and lead.owner_id != ctx.user.id:
        notify(
            db,
            ctx.tenant_id,
            lead.owner_id,
            f"Lead assigned to you: {lead.name}",
            None,
            f"/crm/leads/{lead.id}",
            "lead",
        )
    audit(db, ctx, "lead.updated", "lead", lead.id, before=before, after=snapshot(lead))
    db.commit()
    return LeadOut.model_validate(lead)


@router.delete("/leads/{lid}")
def delete_lead(lid: uuid.UUID, ctx: Ctx = Depends(require("crm.lead.delete"))):
    lead = get_or_404(ctx.db, Lead, lid, ctx.tenant_id, "Lead")
    lead.deleted_at = datetime.now(UTC)
    audit(ctx.db, ctx, "lead.deleted", "lead", lead.id)
    ctx.db.commit()
    return {"ok": True}


# =============================================================== pipelines & opportunities
@router.get("/pipelines")
def list_pipelines(ctx: Ctx = Depends(require("crm.opportunity.read_all", "crm.opportunity.read_own"))):
    db = ctx.db
    out = []
    for p in db.scalars(
        select(Pipeline).where(Pipeline.tenant_id == ctx.tenant_id).order_by(Pipeline.is_default.desc())
    ):
        stages = db.scalars(
            select(PipelineStage).where(PipelineStage.pipeline_id == p.id).order_by(PipelineStage.position)
        )
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "is_default": p.is_default,
                "stages": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "position": s.position,
                        "probability": s.probability,
                        "outcome": s.outcome,
                    }
                    for s in stages
                ],
            }
        )
    return out


class OpportunityIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    account_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    value: Decimal = Field(ZERO, ge=0)
    expected_close: date | None = None
    owner_id: uuid.UUID | None = None


class OpportunityPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    contact_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    value: Decimal | None = Field(None, ge=0)
    expected_close: date | None = None
    owner_id: uuid.UUID | None = None
    version: int | None = None


class OpportunityOut(Entity):
    name: str
    account_id: uuid.UUID
    contact_id: uuid.UUID | None
    pipeline_id: uuid.UUID
    stage_id: uuid.UUID
    value: Decimal
    expected_close: date | None
    owner_id: uuid.UUID | None
    status: str
    closed_at: datetime | None


def _apply_stage(db: Session, ctx: Ctx, opp: Opportunity, stage_id: uuid.UUID) -> None:
    stage = ref_or_422(db, PipelineStage, stage_id, ctx.tenant_id, "stage_id", "Stage")
    opp.pipeline_id, opp.stage_id = stage.pipeline_id, stage.id
    new_status = stage.outcome
    if new_status != opp.status:
        opp.status = new_status
        opp.closed_at = datetime.now(UTC) if new_status in ("won", "lost") else None
        if new_status == "won":
            emit(db, ctx.tenant_id, "opportunity.won", "opportunity", opp.id, {"value": str(opp.value)})


def _opp_rows(db, rows) -> list[dict]:
    accs = dict(
        db.execute(select(Account.id, Account.name).where(Account.id.in_({r.account_id for r in rows}))).all()
    )
    stages = dict(
        db.execute(
            select(PipelineStage.id, PipelineStage.name).where(
                PipelineStage.id.in_({r.stage_id for r in rows})
            )
        ).all()
    )
    return [
        {
            **OpportunityOut.model_validate(r).model_dump(),
            "account_name": accs.get(r.account_id),
            "stage_name": stages.get(r.stage_id),
        }
        for r in rows
    ]


@router.get("/opportunities")
def list_opportunities(
    params: PageParams = Depends(),
    status: str | None = None,
    stage_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(require("crm.opportunity.read_all", "crm.opportunity.read_own")),
):
    q = select(Opportunity).where(Opportunity.tenant_id == ctx.tenant_id, Opportunity.deleted_at.is_(None))
    if ctx.own_only("crm.opportunity"):
        q = q.where(Opportunity.owner_id == ctx.user.id)
    if status:
        q = q.where(Opportunity.status == status)
    if stage_id:
        q = q.where(Opportunity.stage_id == stage_id)
    if account_id:
        q = q.where(Opportunity.account_id == account_id)
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(Opportunity.name,),
        sortable={
            "value": Opportunity.value,
            "expected_close": Opportunity.expected_close,
            "created_at": Opportunity.created_at,
        },
        default_sort=Opportunity.created_at.desc(),
    )
    page["data"] = _opp_rows(ctx.db, page["data"])
    return page


@router.post("/opportunities", status_code=201)
def create_opportunity(body: OpportunityIn, ctx: Ctx = Depends(require("crm.opportunity.create"))):
    db = ctx.db
    acc = get_account(db, ctx.tenant_id, body.account_id)
    ref_or_422(db, Contact, body.contact_id, ctx.tenant_id, "contact_id", "Contact")
    owner = ctx.user.id if ctx.own_only("crm.opportunity") else (body.owner_id or ctx.user.id)
    _ensure_member(db, ctx, owner, "owner_id")
    stage_id = body.stage_id
    if stage_id is None:
        p = db.scalar(
            select(Pipeline).where(Pipeline.tenant_id == ctx.tenant_id).order_by(Pipeline.is_default.desc())
        )
        if p is None:
            raise AppError(409, "NO_PIPELINE", "No pipeline configured.")
        stage_id = db.scalar(
            select(PipelineStage.id).where(PipelineStage.pipeline_id == p.id).order_by(PipelineStage.position)
        )
    opp = Opportunity(
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        name=body.name,
        account_id=acc.id,
        contact_id=body.contact_id,
        value=body.value,
        expected_close=body.expected_close,
        owner_id=owner,
        pipeline_id=uuid.uuid4(),
        stage_id=uuid.uuid4(),
    )
    _apply_stage(db, ctx, opp, stage_id)
    db.add(opp)
    db.flush()
    audit(db, ctx, "opportunity.created", "opportunity", opp.id, after=snapshot(opp))
    db.commit()
    return _opp_rows(db, [opp])[0]


@router.patch("/opportunities/{oid}")
def update_opportunity(
    oid: uuid.UUID, body: OpportunityPatch, ctx: Ctx = Depends(require("crm.opportunity.update"))
):
    db = ctx.db
    opp = get_or_404(db, Opportunity, oid, ctx.tenant_id, "Opportunity")
    _own_guard(ctx, "crm.opportunity", opp.owner_id, "Opportunity")
    before = snapshot(opp)
    if "contact_id" in body.model_fields_set:
        ref_or_422(db, Contact, body.contact_id, ctx.tenant_id, "contact_id", "Contact")
    if "owner_id" in body.model_fields_set:
        _ensure_member(db, ctx, body.owner_id, "owner_id")
    stage_id = body.stage_id
    apply_patch(opp, body, exclude={"stage_id"})
    if stage_id:
        _apply_stage(db, ctx, opp, stage_id)
    audit(db, ctx, "opportunity.updated", "opportunity", opp.id, before=before, after=snapshot(opp))
    db.commit()
    return _opp_rows(db, [opp])[0]


@router.delete("/opportunities/{oid}")
def delete_opportunity(oid: uuid.UUID, ctx: Ctx = Depends(require("crm.opportunity.delete"))):
    opp = get_or_404(ctx.db, Opportunity, oid, ctx.tenant_id, "Opportunity")
    opp.deleted_at = datetime.now(UTC)
    audit(ctx.db, ctx, "opportunity.deleted", "opportunity", opp.id)
    ctx.db.commit()
    return {"ok": True}


# =============================================================== activities & tasks
class ActivityIn(BaseModel):
    type: str
    subject: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    related_type: str | None = None
    related_id: uuid.UUID | None = None
    due_at: datetime | None = None
    priority: str = Field("normal", pattern="^(low|normal|high)$")
    assigned_to: uuid.UUID | None = None
    done: bool = False

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in ACTIVITY_TYPES:
            raise ValueError("Unknown activity type.")
        return v

    @field_validator("related_type")
    @classmethod
    def _r(cls, v):
        if v and v not in RELATED:
            raise ValueError("Unknown related type.")
        return v


class ActivityPatch(BaseModel):
    subject: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    due_at: datetime | None = None
    priority: str | None = Field(None, pattern="^(low|normal|high)$")
    assigned_to: uuid.UUID | None = None
    done: bool | None = None
    version: int | None = None


class ActivityOut(Entity):
    type: str
    subject: str
    description: str | None
    related_type: str | None
    related_id: uuid.UUID | None
    due_at: datetime | None
    done_at: datetime | None
    priority: str
    assigned_to: uuid.UUID | None
    created_by: uuid.UUID | None


_RELATED_MODELS = {"lead": Lead, "account": Account, "contact": Contact, "opportunity": Opportunity}


@router.get("/activities")
def list_activities(
    params: PageParams = Depends(),
    type: str | None = None,
    related_type: str | None = None,
    related_id: uuid.UUID | None = None,
    assigned: str | None = None,
    status: str | None = None,
    ctx: Ctx = Depends(require("crm.activity.read_all", "crm.activity.read_own")),
):
    q = select(Activity).where(Activity.tenant_id == ctx.tenant_id, Activity.deleted_at.is_(None))
    if ctx.own_only("crm.activity") or assigned == "me":
        q = q.where(
            or_(Activity.assigned_to == ctx.user.id, Activity.created_by == ctx.user.id)
            if assigned != "me"
            else Activity.assigned_to == ctx.user.id
        )
    if type:
        q = q.where(Activity.type.in_(type.split(",")))
    if related_type:
        q = q.where(Activity.related_type == related_type)
    if related_id:
        q = q.where(Activity.related_id == related_id)
    if status == "open":
        q = q.where(Activity.done_at.is_(None))
    elif status == "done":
        q = q.where(Activity.done_at.is_not(None))
    elif status == "overdue":
        q = q.where(Activity.done_at.is_(None), Activity.due_at < datetime.now(UTC))
    return paginate(
        ctx.db,
        q,
        params,
        search_cols=(Activity.subject, Activity.description),
        sortable={"due_at": Activity.due_at, "created_at": Activity.created_at},
        default_sort=Activity.created_at.desc(),
        schema=ActivityOut,
    )


@router.post("/activities", response_model=ActivityOut, status_code=201)
def create_activity(body: ActivityIn, ctx: Ctx = Depends(require("crm.activity.create"))):
    db = ctx.db
    if body.related_type in _RELATED_MODELS:
        ref_or_422(
            db,
            _RELATED_MODELS[body.related_type],
            body.related_id,
            ctx.tenant_id,
            "related_id",
            "Related record",
        )
    assignee = body.assigned_to or ctx.user.id
    _ensure_member(db, ctx, assignee, "assigned_to")
    a = Activity(
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        assigned_to=assignee,
        done_at=datetime.now(UTC) if body.done or body.type in ("note",) else None,
        **body.model_dump(exclude={"assigned_to", "done"}),
    )
    db.add(a)
    db.flush()
    if assignee != ctx.user.id and a.type == "task":
        notify(
            db, ctx.tenant_id, assignee, f"New task: {a.subject}", a.description, "/workspace/tasks", "task"
        )
    audit(db, ctx, "activity.created", "activity", a.id, after=snapshot(a))
    db.commit()
    return a


@router.patch("/activities/{aid}", response_model=ActivityOut)
def update_activity(aid: uuid.UUID, body: ActivityPatch, ctx: Ctx = Depends(require("crm.activity.update"))):
    db = ctx.db
    a = get_or_404(db, Activity, aid, ctx.tenant_id, "Activity")
    if ctx.own_only("crm.activity") and ctx.user.id not in (a.assigned_to, a.created_by):
        raise AppError(404, "NOT_FOUND", "Activity not found.")
    if "assigned_to" in body.model_fields_set:
        _ensure_member(db, ctx, body.assigned_to, "assigned_to")
    before = snapshot(a)
    done = body.done
    apply_patch(a, body, exclude={"done"})
    if done is not None:
        a.done_at = datetime.now(UTC) if done else None
    audit(db, ctx, "activity.updated", "activity", a.id, before=before, after=snapshot(a))
    db.commit()
    return a


@router.delete("/activities/{aid}")
def delete_activity(aid: uuid.UUID, ctx: Ctx = Depends(require("crm.activity.delete"))):
    a = get_or_404(ctx.db, Activity, aid, ctx.tenant_id, "Activity")
    a.deleted_at = datetime.now(UTC)
    audit(ctx.db, ctx, "activity.deleted", "activity", a.id)
    ctx.db.commit()
    return {"ok": True}


_ = Integer
