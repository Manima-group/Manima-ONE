from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from manima.core.audit import audit, snapshot
from manima.core.security import Ctx, require, tenant_ctx
from manima.modules.compliance_gst.domain import STATES, validate_gstin
from manima.modules.compliance_gst.models import GstRegistration, HsnSac, NumberSeries
from manima.shared.http import AppError, not_found
from manima.shared.schemas import ORM, Entity

router = APIRouter(prefix="/api/v1", tags=["gst"])


class RegistrationIn(BaseModel):
    gstin: str
    legal_name: str = Field(min_length=2, max_length=200)
    trade_name: str | None = Field(None, max_length=200)
    registration_type: str = Field("regular", pattern="^(regular|composition|sez_unit)$")
    address: dict = {}
    is_default: bool = False

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str) -> str:
        v = v.strip().upper()
        err = validate_gstin(v)
        if err:
            raise ValueError(err)
        return v


class RegistrationOut(Entity):
    gstin: str
    legal_name: str
    trade_name: str | None
    state_code: str
    registration_type: str
    address: dict
    is_default: bool


@router.get("/gst/states")
def states():
    return [{"code": k, "name": v} for k, v in sorted(STATES.items())]


@router.get("/gst/validate-gstin")
def check_gstin(gstin: str):
    err = validate_gstin(gstin)
    return {"valid": err is None, "error": err, "state_code": gstin[:2] if err is None else None}


@router.get("/tenant/gst-registrations", response_model=list[RegistrationOut])
def list_registrations(ctx: Ctx = Depends(tenant_ctx)):
    return ctx.db.scalars(
        select(GstRegistration)
        .where(GstRegistration.tenant_id == ctx.tenant_id)
        .order_by(GstRegistration.is_default.desc(), GstRegistration.created_at)
    ).all()


def _clear_default(ctx: Ctx, keep: uuid.UUID | None) -> None:
    for r in ctx.db.scalars(select(GstRegistration).where(GstRegistration.tenant_id == ctx.tenant_id)):
        if r.id != keep:
            r.is_default = False


@router.post("/tenant/gst-registrations", response_model=RegistrationOut, status_code=201)
def create_registration(body: RegistrationIn, ctx: Ctx = Depends(require("core.gst.manage"))):
    db = ctx.db
    if db.scalar(
        select(GstRegistration.id).where(
            GstRegistration.tenant_id == ctx.tenant_id, GstRegistration.gstin == body.gstin
        )
    ):
        raise AppError(409, "DUPLICATE_GSTIN", "This GSTIN is already registered.")
    first = db.scalar(select(GstRegistration.id).where(GstRegistration.tenant_id == ctx.tenant_id)) is None
    r = GstRegistration(
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        state_code=body.gstin[:2],
        **body.model_dump(exclude={"is_default"}),
        is_default=body.is_default or first,
    )
    db.add(r)
    db.flush()
    if r.is_default:
        _clear_default(ctx, r.id)
    audit(db, ctx, "gst_registration.created", "gst_registration", r.id, after=snapshot(r))
    db.commit()
    return r


@router.patch("/tenant/gst-registrations/{rid}", response_model=RegistrationOut)
def update_registration(rid: uuid.UUID, body: RegistrationIn, ctx: Ctx = Depends(require("core.gst.manage"))):
    db = ctx.db
    r = db.get(GstRegistration, rid)
    if r is None:
        raise not_found("GST registration")
    before = snapshot(r)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    r.state_code = body.gstin[:2]
    r.version += 1
    if r.is_default:
        _clear_default(ctx, r.id)
    audit(db, ctx, "gst_registration.updated", "gst_registration", r.id, before=before, after=snapshot(r))
    db.commit()
    return r


class SeriesOut(Entity):
    gst_registration_id: uuid.UUID | None
    doc_type: str
    financial_year: str
    prefix: str
    padding: int
    next_value: int


class SeriesPatch(BaseModel):
    prefix: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9/\-]+$")
    next_value: int | None = Field(None, ge=1)


@router.get("/tenant/number-series", response_model=list[SeriesOut])
def list_series(ctx: Ctx = Depends(require("core.settings.read", "core.gst.manage"))):
    return ctx.db.scalars(
        select(NumberSeries)
        .where(NumberSeries.tenant_id == ctx.tenant_id)
        .order_by(NumberSeries.doc_type, NumberSeries.financial_year)
    ).all()


@router.patch("/tenant/number-series/{sid}", response_model=SeriesOut)
def update_series(sid: uuid.UUID, body: SeriesPatch, ctx: Ctx = Depends(require("core.gst.manage"))):
    s = ctx.db.get(NumberSeries, sid)
    if s is None:
        raise not_found("Number series")
    if body.next_value is not None and body.next_value < s.next_value:
        raise AppError(
            409, "SERIES_REWIND", "Number series cannot be moved backwards (numbers must stay unique)."
        )
    before = snapshot(s)
    s.prefix = body.prefix
    if body.next_value:
        s.next_value = body.next_value
    audit(ctx.db, ctx, "number_series.updated", "number_series", s.id, before=before, after=snapshot(s))
    ctx.db.commit()
    return s


class HsnOut(ORM):
    code: str
    description: str
    kind: str
    default_rate: float


@router.get("/catalog/hsn-sac", response_model=list[HsnOut])
def hsn_lookup(q: str = "", ctx: Ctx = Depends(require("catalog.item.read"))):
    stmt = select(HsnSac)
    if q:
        stmt = stmt.where(or_(HsnSac.code.ilike(f"{q}%"), HsnSac.description.ilike(f"%{q}%")))
    return ctx.db.scalars(stmt.order_by(HsnSac.code).limit(20)).all()


_ = date
