"""Manima Super Admin (Platform Control Centre). Tenant metadata only — no tenant business data."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select, text

from manima.core.audit import audit
from manima.core.catalogue import MODULES_BY_KEY, PLATFORM_ROLES, TOGGLEABLE_MODULES
from manima.core.models import (
    AuditEvent,
    Feature,
    Module,
    OutboxEvent,
    Plan,
    PlanChange,
    PlanEntitlement,
    PlatformRoleAssignment,
    PlatformUser,
    Role,
    Subscription,
    Tenant,
    TenantFeatureOverride,
    TenantMembership,
    TenantModuleState,
)
from manima.core.provisioning import provision_tenant
from manima.core.security import (
    Ctx,
    hash_password,
    require_platform,
    revoke_user_sessions,
    validate_password_strength,
)
from manima.shared.db import platform_session_factory, set_tenant
from manima.shared.http import AppError, PageParams, not_found

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


def platform_db():
    """Cross-tenant session (BYPASSRLS role). Only for platform metadata: counts, outbox, platform audit."""
    db = platform_session_factory()()
    try:
        yield db
    finally:
        db.close()


def _sub_for(db, tenant_id):
    return db.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == tenant_id)
        .order_by(Subscription.created_at.desc())
    )


def _tenant_row(db, t: Tenant) -> dict:
    sub = _sub_for(db, t.id)
    plan = db.get(Plan, sub.plan_id) if sub else None
    members = db.scalar(
        select(func.count())
        .select_from(TenantMembership)
        .where(TenantMembership.tenant_id == t.id, TenantMembership.status == "active")
    )
    return {
        "id": t.id,
        "slug": t.slug,
        "legal_name": t.legal_name,
        "status": t.status,
        "industry_pack": t.industry_pack,
        "is_sandbox": t.is_sandbox,
        "created_at": t.created_at,
        "members": members,
        "plan": plan.name if plan else None,
        "plan_key": plan.key if plan else None,
        "subscription_status": sub.status if sub else None,
        "trial_ends_at": sub.trial_ends_at if sub else None,
    }


# ---------------------------------------------------------------- dashboard & health
@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(require_platform("platform.tenant.read"))):
    db = ctx.db
    by_status = dict(db.execute(select(Tenant.status, func.count()).group_by(Tenant.status)).all())
    subs = db.execute(select(Subscription.status, func.count()).group_by(Subscription.status)).all()
    mrr = db.scalar(
        select(func.coalesce(func.sum(Plan.price_monthly), 0))
        .select_from(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.status == "active")
    )
    users = db.scalar(select(func.count()).select_from(PlatformUser))
    module_usage = dict(
        db.execute(
            select(TenantModuleState.module_key, func.count())
            .where(TenantModuleState.state == "enabled")
            .group_by(TenantModuleState.module_key)
        ).all()
    )
    since = datetime.now(UTC) - timedelta(days=30)
    signups = db.execute(
        select(func.date_trunc("day", Tenant.created_at).label("d"), func.count())
        .where(Tenant.created_at >= since)
        .group_by("d")
        .order_by("d")
    ).all()
    recent = [
        _tenant_row(db, t) for t in db.scalars(select(Tenant).order_by(Tenant.created_at.desc()).limit(5))
    ]
    pending = db.scalar(select(func.count()).select_from(PlanChange).where(PlanChange.status == "requested"))
    return {
        "tenants": {"total": sum(by_status.values()), "by_status": by_status},
        "subscriptions": dict(subs),
        "mrr": mrr or Decimal("0"),
        "users": users,
        "module_usage": module_usage,
        "signups_30d": [{"day": d.date().isoformat(), "count": c} for d, c in signups],
        "recent_tenants": recent,
        "pending_plan_changes": pending,
    }


@router.get("/health")
def health(
    ctx: Ctx = Depends(require_platform("platform.telemetry.read")), db=Depends(platform_db)
):  # outbox spans tenants; only counts are returned
    checks = {}
    t0 = datetime.now(UTC)
    db.execute(text("select 1"))
    checks["database"] = {
        "status": "ok",
        "latency_ms": round((datetime.now(UTC) - t0).total_seconds() * 1000, 1),
    }
    try:
        import redis

        from manima.settings import get_settings

        r = redis.Redis.from_url(get_settings().redis_url, socket_timeout=1)
        r.ping()
        hb = r.get("manima:worker:heartbeat")
        checks["redis"] = {"status": "ok"}
        age = (datetime.now(UTC).timestamp() - float(hb)) if hb else None
        checks["worker"] = {
            "status": "ok" if age is not None and age < 120 else "down",
            "last_heartbeat_s": round(age, 1) if age is not None else None,
        }
    except Exception as e:  # pragma: no cover - environment dependent
        checks["redis"] = {"status": "down", "error": type(e).__name__}
        checks["worker"] = {"status": "unknown"}
    unpublished = db.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None), OutboxEvent.dead.is_(False))
    )
    oldest = db.scalar(
        select(func.min(OutboxEvent.occurred_at)).where(
            OutboxEvent.published_at.is_(None), OutboxEvent.dead.is_(False)
        )
    )
    dead = db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.dead.is_(True)))
    lag = (datetime.now(UTC) - oldest).total_seconds() if oldest else 0
    checks["outbox"] = {
        "status": "ok" if lag < 300 and not dead else "degraded",
        "unpublished": unpublished,
        "lag_seconds": round(lag, 1),
        "dead_letters": dead,
    }
    overall = "ok" if all(c.get("status") == "ok" for c in checks.values()) else "degraded"
    return {
        "status": overall,
        "checks": checks,
        "modules": [
            {"key": m.key, "version": m.version, "platform_state": m.platform_state}
            for m in db.scalars(select(Module).order_by(Module.key))
        ],
    }


@router.get("/dead-letters")
def dead_letters(ctx: Ctx = Depends(require_platform("platform.telemetry.read")), pdb=Depends(platform_db)):
    rows = pdb.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.dead.is_(True))
        .order_by(OutboxEvent.occurred_at.desc())
        .limit(100)
    )
    return [
        {
            "id": e.id,
            "tenant_id": e.tenant_id,
            "event_type": e.event_type,
            "attempts": e.publish_attempts,
            "last_error": e.last_error,
            "occurred_at": e.occurred_at,
        }
        for e in rows
    ]


@router.post("/dead-letters/{eid}:replay")
def replay_dead_letter(
    eid: uuid.UUID,
    ctx: Ctx = Depends(require_platform("platform.dlq.replay")),
    pdb=Depends(platform_db),
):
    e = pdb.get(OutboxEvent, eid)
    if e is None or not e.dead:
        raise not_found("Dead letter")
    e.dead, e.publish_attempts, e.published_at, e.last_error = False, 0, None, None
    pdb.commit()
    audit(ctx.db, ctx, "dlq.replayed", "outbox_event", e.id, platform=True)
    ctx.db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- tenants
@router.get("/tenants")
def list_tenants(
    params: PageParams = Depends(),
    status: str | None = None,
    ctx: Ctx = Depends(require_platform("platform.tenant.read")),
):
    db = ctx.db
    q = select(Tenant)
    if status:
        q = q.where(Tenant.status == status)
    if params.q:
        q = q.where(or_(Tenant.legal_name.ilike(f"%{params.q}%"), Tenant.slug.ilike(f"%{params.q}%")))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Tenant.created_at.desc()).limit(params.limit).offset(params.offset))
    return {
        "data": [_tenant_row(db, t) for t in rows],
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


class TenantCreate(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    owner_email: EmailStr
    owner_name: str = Field(min_length=2, max_length=120)
    owner_password: str | None = Field(None, max_length=200)
    plan_key: str = "growth"
    trial_days: int | None = Field(14, ge=0, le=90)
    state_code: str | None = Field(None, pattern=r"^[0-9]{2}$")


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantCreate, ctx: Ctx = Depends(require_platform("platform.tenant.create"))):
    db = ctx.db
    email = body.owner_email.lower()
    owner = db.scalar(select(PlatformUser).where(PlatformUser.email == email))
    temp_password = None
    if owner is None:
        pw = body.owner_password
        if pw:
            validate_password_strength(pw)
        else:
            temp_password = pw = "M1-" + secrets.token_urlsafe(9) + "9a"
        owner = PlatformUser(email=email, name=body.owner_name, password_hash=hash_password(pw))
        db.add(owner)
        db.flush()
    tenant = provision_tenant(
        db,
        legal_name=body.legal_name,
        owner=owner,
        plan_key=body.plan_key,
        actor=ctx.user,
        trial_days=body.trial_days or None,
        state_code=body.state_code,
    )
    db.flush()  # tenant-scoped rows must be written while the new tenant's context is active
    set_tenant(db, None)
    audit(
        db,
        ctx,
        "tenant.created",
        "tenant",
        tenant.id,
        after={"slug": tenant.slug, "owner": email, "plan": body.plan_key},
        platform=True,
    )
    db.commit()
    out = _tenant_row(db, tenant)
    out["owner_temp_password"] = temp_password
    return out


def _get_tenant(db, tid) -> Tenant:
    t = db.get(Tenant, tid)
    if t is None:
        raise not_found("Tenant")
    return t


@router.get("/tenants/{tid}")
def tenant_detail(tid: uuid.UUID, ctx: Ctx = Depends(require_platform("platform.tenant.read"))):
    db = ctx.db
    t = _get_tenant(db, tid)
    out = _tenant_row(db, t)
    out["modules"] = [
        {
            "key": s.module_key,
            "name": MODULES_BY_KEY[s.module_key].name,
            "state": s.state,
            "changed_at": s.changed_at,
        }
        for s in db.scalars(
            select(TenantModuleState)
            .where(TenantModuleState.tenant_id == t.id)
            .order_by(TenantModuleState.module_key)
        )
    ]
    out["overrides"] = [
        {"feature_key": o.feature_key, "effect": o.effect, "reason": o.reason, "expires_at": o.expires_at}
        for o in db.scalars(select(TenantFeatureOverride).where(TenantFeatureOverride.tenant_id == t.id))
    ]
    rows = db.execute(
        select(TenantMembership, PlatformUser)
        .join(PlatformUser, PlatformUser.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == t.id)
        .order_by(PlatformUser.name)
    ).all()
    out["members_list"] = [
        {"name": u.name, "email": u.email, "status": m.status, "last_login_at": u.last_login_at}
        for m, u in rows
    ]
    sub = _sub_for(db, t.id)
    out["subscription"] = (
        None
        if not sub
        else {
            "id": sub.id,
            "status": sub.status,
            "plan_id": sub.plan_id,
            "trial_ends_at": sub.trial_ends_at,
            "current_period_end": sub.current_period_end,
        }
    )
    return out


def _set_status(ctx: Ctx, tid: uuid.UUID, status: str, reason: str | None) -> dict:
    db = ctx.db
    t = _get_tenant(db, tid)
    before = t.status
    if before == "closed":
        raise AppError(409, "INVALID_TRANSITION", "Closed tenants cannot be changed.")
    t.status = status
    audit(
        db,
        ctx,
        f"tenant.{'suspended' if status == 'suspended' else 'reactivated'}",
        "tenant",
        t.id,
        before={"status": before},
        after={"status": status, "reason": reason},
        platform=True,
    )
    db.commit()
    return _tenant_row(db, t)


class ReasonIn(BaseModel):
    reason: str | None = Field(None, max_length=300)


@router.post("/tenants/{tid}:suspend")
def suspend_tenant(
    tid: uuid.UUID,
    body: ReasonIn | None = None,
    ctx: Ctx = Depends(require_platform("platform.tenant.create")),
):
    return _set_status(ctx, tid, "suspended", body.reason if body else None)


@router.post("/tenants/{tid}:reactivate")
def reactivate_tenant(
    tid: uuid.UUID,
    body: ReasonIn | None = None,
    ctx: Ctx = Depends(require_platform("platform.tenant.create")),
):
    return _set_status(ctx, tid, "active", body.reason if body else None)


class SubscriptionIn(BaseModel):
    plan_key: str
    status: str = Field("active", pattern="^(trialing|active|past_due|grace|suspended|cancelled)$")
    trial_days: int | None = Field(None, ge=1, le=90)


@router.post("/tenants/{tid}/subscription")
def set_subscription(
    tid: uuid.UUID, body: SubscriptionIn, ctx: Ctx = Depends(require_platform("platform.plan.manage"))
):
    db = ctx.db
    t = _get_tenant(db, tid)
    plan = db.scalar(select(Plan).where(Plan.key == body.plan_key))
    if plan is None:
        raise AppError(422, "PLAN_NOT_FOUND", "Unknown plan.")
    sub = _sub_for(db, t.id)
    before = {"plan_id": str(sub.plan_id), "status": sub.status} if sub else None
    now = datetime.now(UTC)
    if sub is None:
        sub = Subscription(tenant_id=t.id, plan_id=plan.id, current_period_start=now)
        db.add(sub)
    sub.plan_id, sub.status = plan.id, body.status
    sub.trial_ends_at = (
        now + timedelta(days=body.trial_days)
        if body.status == "trialing" and body.trial_days
        else sub.trial_ends_at
    )
    if body.status == "active":
        sub.current_period_start, sub.current_period_end = now, now + timedelta(days=30)
    audit(
        db,
        ctx,
        "subscription.changed",
        "subscription",
        sub.id,
        before=before,
        after={"plan": plan.key, "status": body.status, "tenant": str(t.id)},
        platform=True,
    )
    db.commit()
    return _tenant_row(db, t)


class OverrideIn(BaseModel):
    effect: str = Field(pattern="^(grant|revoke)$")
    reason: str = Field(min_length=3, max_length=300)
    expires_at: datetime | None = None


@router.put("/tenants/{tid}/features/{key}")
def put_override(
    tid: uuid.UUID,
    key: str,
    body: OverrideIn,
    ctx: Ctx = Depends(require_platform("platform.override.manage")),
):
    db = ctx.db
    _get_tenant(db, tid)
    if db.get(Feature, key) is None:
        raise not_found("Feature")
    o = db.get(TenantFeatureOverride, (tid, key))
    if o is None:
        o = TenantFeatureOverride(tenant_id=tid, feature_key=key)
        db.add(o)
    o.effect, o.reason, o.expires_at, o.created_by = body.effect, body.reason, body.expires_at, ctx.user.id
    audit(
        db,
        ctx,
        "override.set",
        "tenant_feature_override",
        f"{tid}:{key}",
        after={"effect": body.effect, "reason": body.reason},
        platform=True,
    )
    db.commit()
    return {"ok": True}


@router.delete("/tenants/{tid}/features/{key}")
def delete_override(
    tid: uuid.UUID, key: str, ctx: Ctx = Depends(require_platform("platform.override.manage"))
):
    o = ctx.db.get(TenantFeatureOverride, (tid, key))
    if o is None:
        raise not_found("Override")
    ctx.db.delete(o)
    audit(ctx.db, ctx, "override.removed", "tenant_feature_override", f"{tid}:{key}", platform=True)
    ctx.db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- plans
class PlanIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(None, max_length=300)
    price_monthly: Decimal = Field(ge=0)
    max_users: int | None = Field(None, ge=1)
    modules: list[str]
    active: bool = True


class PlanPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    description: str | None = Field(None, max_length=300)
    price_monthly: Decimal | None = Field(None, ge=0)
    max_users: int | None = Field(None, ge=1)
    modules: list[str] | None = None
    active: bool | None = None


def _plan_out(db, p: Plan) -> dict:
    mods = db.scalars(select(PlanEntitlement.feature_key).where(PlanEntitlement.plan_id == p.id)).all()
    tenants = db.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(
            Subscription.plan_id == p.id, Subscription.status.in_(("trialing", "active", "past_due", "grace"))
        )
    )
    return {
        "id": p.id,
        "key": p.key,
        "name": p.name,
        "description": p.description,
        "price_monthly": p.price_monthly,
        "max_users": p.max_users,
        "active": p.active,
        "modules": sorted(mods),
        "tenants": tenants,
    }


def _set_plan_modules(db, plan: Plan, modules: list[str]) -> None:
    bad = [m for m in modules if m not in TOGGLEABLE_MODULES]
    if bad:
        raise AppError(422, "INVALID_MODULE", f"Unknown modules: {', '.join(bad)}")
    db.execute(PlanEntitlement.__table__.delete().where(PlanEntitlement.plan_id == plan.id))
    for m in sorted(set(modules)):
        db.add(PlanEntitlement(plan_id=plan.id, feature_key=m, limits={}))


@router.get("/plans")
def list_plans(ctx: Ctx = Depends(require_platform("platform.tenant.read"))):
    return [_plan_out(ctx.db, p) for p in ctx.db.scalars(select(Plan).order_by(Plan.price_monthly))]


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, ctx: Ctx = Depends(require_platform("platform.plan.manage"))):
    db = ctx.db
    if db.scalar(select(Plan.id).where(Plan.key == body.key)):
        raise AppError(409, "PLAN_EXISTS", "A plan with this key exists.")
    p = Plan(**body.model_dump(exclude={"modules"}))
    db.add(p)
    db.flush()
    _set_plan_modules(db, p, body.modules)
    audit(db, ctx, "plan.created", "plan", p.id, after=body.model_dump(mode="json"), platform=True)
    db.commit()
    return _plan_out(db, p)


@router.patch("/plans/{pid}")
def update_plan(
    pid: uuid.UUID, body: PlanPatch, ctx: Ctx = Depends(require_platform("platform.plan.manage"))
):
    db = ctx.db
    p = db.get(Plan, pid)
    if p is None:
        raise not_found("Plan")
    before = _plan_out(db, p)
    for k, v in body.model_dump(exclude_unset=True, exclude={"modules"}).items():
        setattr(p, k, v)
    if body.modules is not None:
        _set_plan_modules(db, p, body.modules)
    db.flush()
    after = _plan_out(db, p)
    audit(db, ctx, "plan.updated", "plan", p.id, before=before, after=after, platform=True)
    db.commit()
    return after


@router.get("/plan-changes")
def list_plan_changes(ctx: Ctx = Depends(require_platform("platform.tenant.read"))):
    db = ctx.db
    rows = db.scalars(select(PlanChange).order_by(PlanChange.created_at.desc()).limit(100))
    plans = {p.id: p.name for p in db.scalars(select(Plan))}
    out = []
    for pc in rows:
        t = db.get(Tenant, pc.tenant_id)
        out.append(
            {
                "id": pc.id,
                "tenant_id": pc.tenant_id,
                "tenant": t.legal_name if t else None,
                "from_plan": plans.get(pc.from_plan_id),
                "to_plan": plans.get(pc.to_plan_id),
                "status": pc.status,
                "note": pc.note,
                "created_at": pc.created_at,
            }
        )
    return out


@router.post("/plan-changes/{pcid}:{decision}")
def decide_plan_change(
    pcid: uuid.UUID, decision: str, ctx: Ctx = Depends(require_platform("platform.plan.manage"))
):
    if decision not in ("approve", "reject"):
        raise not_found()
    db = ctx.db
    pc = db.get(PlanChange, pcid)
    if pc is None or pc.status != "requested":
        raise not_found("Plan change")
    pc.status, pc.decided_by = ("approved" if decision == "approve" else "rejected"), ctx.user.id
    if decision == "approve":
        sub = db.get(Subscription, pc.subscription_id)
        sub.plan_id, pc.effective_at = pc.to_plan_id, datetime.now(UTC)
        if sub.status == "trialing":
            sub.status = "active"
    audit(
        db,
        ctx,
        f"plan_change.{pc.status}",
        "plan_change",
        pc.id,
        after={"tenant": str(pc.tenant_id)},
        platform=True,
    )
    db.commit()
    return {"ok": True, "status": pc.status}


# ---------------------------------------------------------------- modules & feature flags
@router.get("/modules")
def registry(ctx: Ctx = Depends(require_platform("platform.tenant.read"))):
    db = ctx.db
    enabled = dict(
        db.execute(
            select(TenantModuleState.module_key, func.count())
            .where(TenantModuleState.state == "enabled")
            .group_by(TenantModuleState.module_key)
        ).all()
    )
    out = []
    for m in db.scalars(select(Module).order_by(Module.key)):
        f = db.get(Feature, m.key)
        out.append(
            {
                "key": m.key,
                "name": m.name,
                "description": m.description,
                "version": m.version,
                "kind": m.kind,
                "depends_on": m.depends_on,
                "platform_state": m.platform_state,
                "tenants_enabled": enabled.get(m.key, 0),
                "feature": None
                if f is None
                else {"enabled": f.enabled, "kill_switch": f.kill_switch, "rule": f.rule},
            }
        )
    return out


class ModulePatch(BaseModel):
    platform_state: str = Field(pattern="^(registered|available|deprecated|retired)$")


@router.patch("/modules/{key}")
def publish_module(
    key: str, body: ModulePatch, ctx: Ctx = Depends(require_platform("platform.module.publish"))
):
    m = ctx.db.get(Module, key)
    if m is None or m.kind == "core":
        raise not_found("Module")
    before = m.platform_state
    m.platform_state = body.platform_state
    audit(
        ctx.db,
        ctx,
        "module.platform_state_changed",
        "module",
        key,
        before={"state": before},
        after={"state": body.platform_state},
        platform=True,
    )
    ctx.db.commit()
    return {"key": key, "platform_state": m.platform_state}


class FeaturePatch(BaseModel):
    enabled: bool | None = None
    kill_switch: bool | None = None
    rule: dict | None = None


@router.patch("/features/{key}")
def patch_feature(
    key: str, body: FeaturePatch, ctx: Ctx = Depends(require_platform("platform.feature_flag.manage"))
):
    f = ctx.db.get(Feature, key)
    if f is None:
        raise not_found("Feature")
    before = {"enabled": f.enabled, "kill_switch": f.kill_switch}
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(f, k, v)
    f.updated_by = ctx.user.id
    audit(
        ctx.db,
        ctx,
        "feature_flag.changed",
        "feature",
        key,
        before=before,
        after={"enabled": f.enabled, "kill_switch": f.kill_switch},
        platform=True,
    )
    ctx.db.commit()
    return {"key": key, "enabled": f.enabled, "kill_switch": f.kill_switch}


# ---------------------------------------------------------------- platform users
def _platform_user_out(db, u: PlatformUser) -> dict:
    roles = db.scalars(
        select(Role.key)
        .join(PlatformRoleAssignment, PlatformRoleAssignment.role_id == Role.id)
        .where(PlatformRoleAssignment.user_id == u.id)
    ).all()
    tenants = db.scalar(
        select(func.count())
        .select_from(TenantMembership)
        .where(TenantMembership.user_id == u.id, TenantMembership.status == "active")
    )
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "status": u.status,
        "platform_roles": sorted(roles),
        "tenants": tenants,
        "last_login_at": u.last_login_at,
        "created_at": u.created_at,
    }


@router.get("/users")
def list_users(
    params: PageParams = Depends(),
    staff_only: bool = False,
    ctx: Ctx = Depends(require_platform("platform.tenant.read")),
):
    db = ctx.db
    q = select(PlatformUser)
    if staff_only:
        q = q.where(PlatformUser.id.in_(select(PlatformRoleAssignment.user_id)))
    if params.q:
        q = q.where(or_(PlatformUser.email.ilike(f"%{params.q}%"), PlatformUser.name.ilike(f"%{params.q}%")))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(PlatformUser.created_at.desc()).limit(params.limit).offset(params.offset))
    return {
        "data": [_platform_user_out(db, u) for u in rows],
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


class PlatformUserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=200)
    platform_roles: list[str] = []


class PlatformUserPatch(BaseModel):
    status: str | None = Field(None, pattern="^(active|disabled)$")
    platform_roles: list[str] | None = None


def _assign_platform_roles(db, user_id, keys: list[str]) -> None:
    bad = [k for k in keys if k not in PLATFORM_ROLES]
    if bad:
        raise AppError(422, "INVALID_ROLE", f"Unknown platform roles: {', '.join(bad)}")
    db.execute(PlatformRoleAssignment.__table__.delete().where(PlatformRoleAssignment.user_id == user_id))
    for k in set(keys):
        rid = db.scalar(select(Role.id).where(Role.tenant_id.is_(None), Role.key == k))
        db.add(PlatformRoleAssignment(user_id=user_id, role_id=rid))


@router.post("/users", status_code=201)
def create_platform_user(body: PlatformUserIn, ctx: Ctx = Depends(require_platform("platform.user.manage"))):
    db = ctx.db
    validate_password_strength(body.password)
    if db.scalar(select(PlatformUser.id).where(PlatformUser.email == body.email.lower())):
        raise AppError(409, "EMAIL_TAKEN", "A user with this email exists.")
    u = PlatformUser(
        email=body.email.lower(),
        name=body.name,
        password_hash=hash_password(body.password),
        mfa_required=bool(body.platform_roles),
    )
    db.add(u)
    db.flush()
    _assign_platform_roles(db, u.id, body.platform_roles)
    audit(
        db,
        ctx,
        "platform_user.created",
        "platform_user",
        u.id,
        after={"email": u.email, "roles": body.platform_roles},
        platform=True,
    )
    db.commit()
    return _platform_user_out(db, u)


@router.patch("/users/{uid}")
def update_platform_user(
    uid: uuid.UUID, body: PlatformUserPatch, ctx: Ctx = Depends(require_platform("platform.user.manage"))
):
    db = ctx.db
    u = db.get(PlatformUser, uid)
    if u is None:
        raise not_found("User")
    if u.id == ctx.user.id and (
        body.status == "disabled"
        or (body.platform_roles is not None and "super_admin" not in body.platform_roles)
    ):
        raise AppError(409, "CANNOT_DEMOTE_SELF", "You cannot disable or demote yourself.")
    before = _platform_user_out(db, u)
    if body.status:
        u.status = body.status
        if body.status == "disabled":
            revoke_user_sessions(db, u.id)
    if body.platform_roles is not None:
        _assign_platform_roles(db, u.id, body.platform_roles)
    db.flush()
    after = _platform_user_out(db, u)
    audit(db, ctx, "platform_user.updated", "platform_user", u.id, before=before, after=after, platform=True)
    db.commit()
    return after


# ---------------------------------------------------------------- platform audit
@router.get("/audit")
def platform_audit(
    params: PageParams = Depends(),
    action: str | None = None,
    ctx: Ctx = Depends(require_platform("platform.audit.read")),
    db=Depends(platform_db),
):
    q = select(AuditEvent).where(AuditEvent.tenant_id.is_(None))
    if action:
        q = q.where(AuditEvent.action.ilike(f"{action}%"))
    if params.q:
        q = q.where(
            or_(AuditEvent.action.ilike(f"%{params.q}%"), AuditEvent.actor_email.ilike(f"%{params.q}%"))
        )
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditEvent.occurred_at.desc()).limit(params.limit).offset(params.offset))
    return {
        "data": [
            {
                "id": a.id,
                "actor_email": a.actor_email,
                "action": a.action,
                "resource_type": a.resource_type,
                "resource_id": a.resource_id,
                "before": a.before,
                "after": a.after,
                "occurred_at": a.occurred_at,
            }
            for a in rows
        ],
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }
