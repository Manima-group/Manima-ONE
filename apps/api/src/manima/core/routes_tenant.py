"""Company Admin: profile/settings, employees, invitations, roles, modules, subscription, audit."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select

from manima.core.audit import audit, emit, notify, snapshot
from manima.core.catalogue import MODULES, MODULES_BY_KEY, TOGGLEABLE_MODULES, all_tenant_permissions
from manima.core.models import (
    AuditEvent,
    Invitation,
    MemberRole,
    Module,
    Plan,
    PlanChange,
    PlanEntitlement,
    PlatformUser,
    Role,
    RolePermission,
    Subscription,
    TenantMembership,
    TenantSettings,
)
from manima.core.provisioning import change_module_state
from manima.core.security import Ctx, require, revoke_user_sessions, sha256, tenant_ctx
from manima.settings import get_settings
from manima.shared.http import AppError, PageParams, not_found, paginate
from manima.shared.schemas import ORM

router = APIRouter(prefix="/api/v1/tenant", tags=["company-admin"])


# ---------------------------------------------------------------- settings / company profile
class SettingsOut(ORM):
    display_name: str
    email: str | None
    phone: str | None
    website: str | None
    address: dict
    state_code: str | None
    pan: str | None
    logo_url: str | None
    fiscal_year_start_month: int
    currency: str
    time_zone: str
    locale: str
    date_format: str
    allow_negative_stock: bool
    quote_validity_days: int
    discount_approval_limit: Decimal
    invoice_terms: str | None
    version: int


class SettingsIn(BaseModel):
    display_name: str | None = Field(None, min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    website: str | None = Field(None, max_length=200)
    address: dict | None = None
    state_code: str | None = Field(None, pattern=r"^[0-9]{2}$")
    pan: str | None = Field(None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    logo_url: str | None = Field(None, max_length=500)
    fiscal_year_start_month: int | None = Field(None, ge=1, le=12)
    time_zone: str | None = None
    date_format: str | None = None
    allow_negative_stock: bool | None = None
    quote_validity_days: int | None = Field(None, ge=1, le=365)
    discount_approval_limit: Decimal | None = Field(None, ge=0, le=100)
    invoice_terms: str | None = Field(None, max_length=4000)
    version: int | None = None


@router.get("/settings", response_model=SettingsOut)
def get_company(ctx: Ctx = Depends(require("core.settings.read", "core.settings.manage"))):
    return ctx.db.get(TenantSettings, ctx.tenant_id)


@router.patch("/settings", response_model=SettingsOut)
def update_company(body: SettingsIn, ctx: Ctx = Depends(require("core.settings.manage"))):
    s = ctx.db.get(TenantSettings, ctx.tenant_id)
    if body.version is not None and body.version != s.version:
        raise AppError(409, "VERSION_CONFLICT", "Settings were changed by someone else. Reload and retry.")
    before = snapshot(s)
    for k, v in body.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(s, k, v)
    s.version += 1
    if body.display_name:
        ctx.tenant.legal_name = body.display_name
    audit(ctx.db, ctx, "company.updated", "tenant_settings", ctx.tenant_id, before=before, after=snapshot(s))
    ctx.db.commit()
    return s


# ---------------------------------------------------------------- members
def _member_out(db, m: TenantMembership, u: PlatformUser) -> dict:
    roles = db.execute(
        select(Role.id, Role.key, Role.name)
        .join(MemberRole, MemberRole.role_id == Role.id)
        .where(MemberRole.membership_id == m.id)
    ).all()
    return {
        "id": m.id,
        "user_id": u.id,
        "name": u.name,
        "email": u.email,
        "phone": u.phone,
        "status": m.status,
        "title": m.title,
        "department": m.department,
        "joined_at": m.joined_at,
        "last_login_at": u.last_login_at,
        "roles": [{"id": r.id, "key": r.key, "name": r.name} for r in roles],
    }


@router.get("/members")
def list_members(
    params: PageParams = Depends(),
    status: str | None = None,
    role_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(require("core.member.read", "core.member.manage")),
):
    db = ctx.db
    q = (
        select(TenantMembership, PlatformUser)
        .join(PlatformUser, PlatformUser.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == ctx.tenant_id)
    )
    if status:
        q = q.where(TenantMembership.status == status)
    if role_id:
        q = q.where(
            TenantMembership.id.in_(select(MemberRole.membership_id).where(MemberRole.role_id == role_id))
        )
    if params.q:
        like = f"%{params.q}%"
        q = q.where(
            or_(
                PlatformUser.name.ilike(like),
                PlatformUser.email.ilike(like),
                TenantMembership.title.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.order_by(PlatformUser.name).limit(params.limit).offset(params.offset)).all()
    return {
        "data": [_member_out(db, m, u) for m, u in rows],
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get("/members/options")
def member_options(ctx: Ctx = Depends(tenant_ctx)):
    """Lightweight list for owner/assignee pickers (any member may see colleagues' names)."""
    rows = ctx.db.execute(
        select(TenantMembership.user_id, PlatformUser.name, PlatformUser.email)
        .join(PlatformUser, PlatformUser.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.status == "active")
        .order_by(PlatformUser.name)
    ).all()
    return [{"id": r.user_id, "name": r.name, "email": r.email} for r in rows]


class MemberPatch(BaseModel):
    role_ids: list[uuid.UUID] | None = None
    status: str | None = Field(None, pattern="^(active|removed)$")
    title: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)


def _owner_role_id(db, tenant_id) -> uuid.UUID:
    return db.scalar(select(Role.id).where(Role.tenant_id == tenant_id, Role.key == "owner"))


def _caller_is_owner(ctx: Ctx) -> bool:
    keys = ctx.db.scalars(
        select(Role.key)
        .join(MemberRole, MemberRole.role_id == Role.id)
        .where(MemberRole.membership_id == ctx.membership.id)
    )
    return "owner" in set(keys)


def _active_owner_count(db, tenant_id) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(MemberRole)
            .join(TenantMembership, TenantMembership.id == MemberRole.membership_id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == "active",
                MemberRole.role_id == _owner_role_id(db, tenant_id),
            )
        )
        or 0
    )


@router.patch("/members/{mid}")
def update_member(mid: uuid.UUID, body: MemberPatch, ctx: Ctx = Depends(require("core.member.manage"))):
    db = ctx.db
    m = db.get(TenantMembership, mid)
    if m is None or m.tenant_id != ctx.tenant_id:
        raise not_found("Member")
    u = db.get(PlatformUser, m.user_id)
    before = _member_out(db, m, u)
    owner_id = _owner_role_id(db, ctx.tenant_id)
    current_roles = {r["id"] for r in before["roles"]}
    is_owner = owner_id in current_roles
    caller_is_owner = _caller_is_owner(ctx)
    if body.role_ids is not None:
        valid = set(
            db.scalars(select(Role.id).where(Role.tenant_id == ctx.tenant_id, Role.id.in_(body.role_ids)))
        )
        if valid != set(body.role_ids):
            raise AppError(
                422,
                "INVALID_ROLE",
                "One or more roles do not exist.",
                [{"field": "role_ids", "issue": "invalid"}],
            )
        if (owner_id in valid) != is_owner and not caller_is_owner:
            raise AppError(403, "OWNER_REQUIRED", "Only an Owner can grant or remove the Owner role.")
        if is_owner and owner_id not in valid and _active_owner_count(db, ctx.tenant_id) <= 1:
            raise AppError(409, "LAST_OWNER", "At least one active Owner must remain.")
        db.execute(MemberRole.__table__.delete().where(MemberRole.membership_id == m.id))
        for rid in valid:
            db.add(MemberRole(membership_id=m.id, role_id=rid))
        revoke_user_sessions(db, m.user_id, ctx.tenant_id) if m.user_id != ctx.user.id else None
    if body.status and body.status != m.status:
        if body.status == "removed":
            if m.user_id == ctx.user.id:
                raise AppError(409, "CANNOT_REMOVE_SELF", "You cannot remove yourself.")
            if is_owner and _active_owner_count(db, ctx.tenant_id) <= 1:
                raise AppError(409, "LAST_OWNER", "At least one active Owner must remain.")
            revoke_user_sessions(db, m.user_id, ctx.tenant_id)
        m.status = body.status
    if body.title is not None:
        m.title = body.title
    if body.department is not None:
        m.department = body.department
    db.flush()
    after = _member_out(db, m, u)
    audit(db, ctx, "member.updated", "membership", m.id, before=before, after=after)
    db.commit()
    return after


# ---------------------------------------------------------------- invitations
class InviteIn(BaseModel):
    email: EmailStr
    name: str | None = Field(None, max_length=120)
    role_ids: list[uuid.UUID] = Field(min_length=1)


def _seat_usage(db, tenant_id) -> tuple[int, int | None]:
    active = (
        db.scalar(
            select(func.count())
            .select_from(TenantMembership)
            .where(TenantMembership.tenant_id == tenant_id, TenantMembership.status == "active")
        )
        or 0
    )
    pending = (
        db.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.tenant_id == tenant_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > datetime.now(UTC),
            )
        )
        or 0
    )
    sub = db.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == tenant_id)
        .order_by(Subscription.created_at.desc())
    )
    plan = db.get(Plan, sub.plan_id) if sub else None
    return active + pending, plan.max_users if plan else None


@router.get("/invitations")
def list_invitations(ctx: Ctx = Depends(require("core.member.manage"))):
    rows = ctx.db.scalars(
        select(Invitation)
        .where(
            Invitation.tenant_id == ctx.tenant_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .order_by(Invitation.created_at.desc())
    )
    roles = {r.id: r.name for r in ctx.db.scalars(select(Role).where(Role.tenant_id == ctx.tenant_id))}
    now = datetime.now(UTC)
    return [
        {
            "id": i.id,
            "email": i.email,
            "name": i.name,
            "roles": [roles.get(r) for r in i.role_ids],
            "expires_at": i.expires_at,
            "expired": i.expires_at < now,
            "created_at": i.created_at,
        }
        for i in rows
    ]


@router.post("/invitations", status_code=201)
def invite(body: InviteIn, ctx: Ctx = Depends(require("core.member.manage"))):
    db = ctx.db
    email = body.email.lower()
    used, limit = _seat_usage(db, ctx.tenant_id)
    if limit is not None and used >= limit:
        raise AppError(
            403,
            "LIMIT_REACHED",
            f"Your plan allows {limit} users. Upgrade to invite more.",
            action_hint="upgrade_plan",
        )
    existing_member = db.scalar(
        select(TenantMembership)
        .join(PlatformUser, PlatformUser.id == TenantMembership.user_id)
        .where(
            TenantMembership.tenant_id == ctx.tenant_id,
            PlatformUser.email == email,
            TenantMembership.status == "active",
        )
    )
    if existing_member:
        raise AppError(409, "ALREADY_MEMBER", "This person is already an employee.")
    valid = set(
        db.scalars(select(Role.id).where(Role.tenant_id == ctx.tenant_id, Role.id.in_(body.role_ids)))
    )
    if valid != set(body.role_ids):
        raise AppError(
            422,
            "INVALID_ROLE",
            "One or more roles do not exist.",
            [{"field": "role_ids", "issue": "invalid"}],
        )
    owner_id = _owner_role_id(db, ctx.tenant_id)
    if owner_id in valid and not _caller_is_owner(ctx):
        raise AppError(403, "OWNER_REQUIRED", "Only an Owner can invite another Owner.")
    for old in db.scalars(
        select(Invitation).where(
            Invitation.tenant_id == ctx.tenant_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
    ):
        old.revoked_at = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    inv = Invitation(
        tenant_id=ctx.tenant_id,
        email=email,
        name=body.name,
        role_ids=list(valid),
        token_hash=sha256(token),
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().invitation_ttl_days),
        invited_by=ctx.user.id,
    )
    db.add(inv)
    db.flush()
    audit(db, ctx, "invitation.created", "invitation", inv.id, after={"email": email})
    emit(
        db,
        ctx.tenant_id,
        "invitation.created",
        "invitation",
        inv.id,
        {"email": email, "accept_path": f"/invite/{token}", "company": ctx.tenant.legal_name},
    )
    db.commit()
    return {"id": inv.id, "email": email, "expires_at": inv.expires_at, "accept_path": f"/invite/{token}"}


@router.delete("/invitations/{iid}")
def revoke_invitation(iid: uuid.UUID, ctx: Ctx = Depends(require("core.member.manage"))):
    inv = ctx.db.get(Invitation, iid)
    if inv is None or inv.tenant_id != ctx.tenant_id:
        raise not_found("Invitation")
    inv.revoked_at = datetime.now(UTC)
    audit(ctx.db, ctx, "invitation.revoked", "invitation", inv.id)
    ctx.db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- roles & permissions
class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(None, max_length=300)
    permissions: list[str]


class RolePatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    description: str | None = Field(None, max_length=300)
    permissions: list[str] | None = None


def _role_out(db, r: Role) -> dict:
    perms = sorted(db.scalars(select(RolePermission.permission_key).where(RolePermission.role_id == r.id)))
    members = db.scalar(
        select(func.count())
        .select_from(MemberRole)
        .join(TenantMembership, TenantMembership.id == MemberRole.membership_id)
        .where(MemberRole.role_id == r.id, TenantMembership.status == "active")
    )
    return {
        "id": r.id,
        "key": r.key,
        "name": r.name,
        "description": r.description,
        "is_system": r.is_system,
        "permissions": perms,
        "member_count": members,
    }


def _validate_perms(perms: list[str]) -> list[str]:
    catalogue = all_tenant_permissions()
    bad = [p for p in perms if p not in catalogue]
    if bad:
        raise AppError(
            422,
            "INVALID_PERMISSION",
            f"Unknown permissions: {', '.join(bad)}",
            [{"field": "permissions", "issue": "invalid"}],
        )
    return sorted(set(perms))


@router.get("/roles")
def list_roles(ctx: Ctx = Depends(require("core.role.manage", "core.member.manage", "core.member.read"))):
    return [
        _role_out(ctx.db, r)
        for r in ctx.db.scalars(
            select(Role).where(Role.tenant_id == ctx.tenant_id).order_by(Role.is_system.desc(), Role.name)
        )
    ]


@router.post("/roles", status_code=201)
def create_role(body: RoleIn, ctx: Ctx = Depends(require("core.role.manage"))):
    db = ctx.db
    perms = _validate_perms(body.permissions)
    key = "custom_" + uuid.uuid4().hex[:8]
    if db.scalar(
        select(Role.id).where(Role.tenant_id == ctx.tenant_id, func.lower(Role.name) == body.name.lower())
    ):
        raise AppError(409, "ROLE_EXISTS", "A role with this name already exists.")
    r = Role(tenant_id=ctx.tenant_id, key=key, name=body.name, description=body.description, is_system=False)
    db.add(r)
    db.flush()
    for p in perms:
        db.add(RolePermission(role_id=r.id, permission_key=p))
    db.flush()
    audit(db, ctx, "role.created", "role", r.id, after={"name": r.name, "permissions": perms})
    emit(db, ctx.tenant_id, "entitlements.changed", "role", r.id)
    db.commit()
    return _role_out(db, r)


@router.patch("/roles/{rid}")
def update_role(rid: uuid.UUID, body: RolePatch, ctx: Ctx = Depends(require("core.role.manage"))):
    db = ctx.db
    r = db.get(Role, rid)
    if r is None or r.tenant_id != ctx.tenant_id:
        raise not_found("Role")
    if r.key == "owner":
        raise AppError(409, "PROTECTED_ROLE", "The Owner role cannot be edited.")
    before = _role_out(db, r)
    if body.name:
        r.name = body.name
    if body.description is not None:
        r.description = body.description
    if body.permissions is not None:
        perms = _validate_perms(body.permissions)
        db.execute(RolePermission.__table__.delete().where(RolePermission.role_id == r.id))
        for p in perms:
            db.add(RolePermission(role_id=r.id, permission_key=p))
    db.flush()
    after = _role_out(db, r)
    audit(db, ctx, "role.updated", "role", r.id, before=before, after=after)
    emit(db, ctx.tenant_id, "entitlements.changed", "role", r.id)
    db.commit()
    return after


@router.delete("/roles/{rid}")
def delete_role(rid: uuid.UUID, ctx: Ctx = Depends(require("core.role.manage"))):
    db = ctx.db
    r = db.get(Role, rid)
    if r is None or r.tenant_id != ctx.tenant_id:
        raise not_found("Role")
    if r.is_system:
        raise AppError(409, "PROTECTED_ROLE", "Default roles cannot be deleted.")
    if _role_out(db, r)["member_count"]:
        raise AppError(409, "ROLE_IN_USE", "Remove this role from all employees first.")
    audit(db, ctx, "role.deleted", "role", r.id, before={"name": r.name})
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.get("/permissions")
def permission_catalogue(ctx: Ctx = Depends(require("core.role.manage", "core.member.manage"))):
    return [
        {
            "module": m.key,
            "name": m.name,
            "permissions": [{"key": k, "description": d} for k, d in m.permissions.items()],
        }
        for m in MODULES
    ]


# ---------------------------------------------------------------- modules
class ModuleStateIn(BaseModel):
    state: str = Field(pattern="^(enabled|read_only|disabled)$")
    reason: str = Field(min_length=3, max_length=300)


@router.get("/modules")
def list_modules(ctx: Ctx = Depends(tenant_ctx)):
    ent = ctx.ent
    out = []
    for key in TOGGLEABLE_MODULES:
        m = MODULES_BY_KEY[key]
        reg = ctx.db.get(Module, key)
        ok, code = ent.module_available(key)
        out.append(
            {
                "key": key,
                "name": m.name,
                "description": m.description,
                "kind": m.kind,
                "depends_on": list(m.depends_on),
                "state": ent.module_states.get(key, "disabled"),
                "entitled": ent.entitled(key),
                "platform_state": reg.platform_state if reg else "registered",
                "writable": ok,
                "reason": code,
            }
        )
    return out


@router.patch("/modules/{key}")
def set_module_state(key: str, body: ModuleStateIn, ctx: Ctx = Depends(require("core.module.manage"))):
    st = change_module_state(ctx.db, ctx, ctx.tenant, key, body.state, body.reason, ctx.ent)
    ctx.db.commit()
    return {"key": key, "state": st.state}


# ---------------------------------------------------------------- subscription
@router.get("/subscription")
def my_subscription(ctx: Ctx = Depends(require("core.billing.read", "core.settings.manage"))):
    db = ctx.db
    sub = db.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == ctx.tenant_id)
        .order_by(Subscription.created_at.desc())
    )
    plan = db.get(Plan, sub.plan_id) if sub else None
    used, limit = _seat_usage(db, ctx.tenant_id)
    plans = []
    for p in db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.price_monthly)):
        mods = db.scalars(select(PlanEntitlement.feature_key).where(PlanEntitlement.plan_id == p.id)).all()
        plans.append(
            {
                "id": p.id,
                "key": p.key,
                "name": p.name,
                "description": p.description,
                "price_monthly": p.price_monthly,
                "max_users": p.max_users,
                "modules": sorted(mods),
            }
        )
    pending = db.scalar(
        select(PlanChange).where(PlanChange.tenant_id == ctx.tenant_id, PlanChange.status == "requested")
    )
    return {
        "subscription": None
        if not sub
        else {
            "id": sub.id,
            "status": sub.status,
            "billing_cycle": sub.billing_cycle,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "trial_ends_at": sub.trial_ends_at,
        },
        "plan": None
        if not plan
        else {
            "id": plan.id,
            "key": plan.key,
            "name": plan.name,
            "price_monthly": plan.price_monthly,
            "max_users": plan.max_users,
        },
        "usage": {"seats_used": used, "seats_limit": limit},
        "plans": plans,
        "pending_change": None
        if not pending
        else {"id": pending.id, "to_plan_id": pending.to_plan_id, "created_at": pending.created_at},
    }


class PlanChangeIn(BaseModel):
    plan_key: str
    note: str | None = Field(None, max_length=300)


@router.post("/subscription:request-change", status_code=201)
def request_plan_change(body: PlanChangeIn, ctx: Ctx = Depends(require("core.billing.read"))):
    db = ctx.db
    sub = db.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == ctx.tenant_id)
        .order_by(Subscription.created_at.desc())
    )
    plan = db.scalar(select(Plan).where(Plan.key == body.plan_key, Plan.active.is_(True)))
    if plan is None or sub is None:
        raise AppError(422, "PLAN_NOT_FOUND", "Unknown plan.")
    if plan.id == sub.plan_id:
        raise AppError(409, "SAME_PLAN", "You are already on this plan.")
    if db.scalar(
        select(PlanChange.id).where(PlanChange.tenant_id == ctx.tenant_id, PlanChange.status == "requested")
    ):
        raise AppError(409, "CHANGE_PENDING", "A plan change is already pending review.")
    pc = PlanChange(
        tenant_id=ctx.tenant_id,
        subscription_id=sub.id,
        from_plan_id=sub.plan_id,
        to_plan_id=plan.id,
        note=body.note,
        requested_by=ctx.user.id,
    )
    db.add(pc)
    db.flush()
    audit(db, ctx, "subscription.change_requested", "plan_change", pc.id, after={"to": plan.key})
    db.commit()
    return {"id": pc.id, "status": pc.status}


# ---------------------------------------------------------------- audit
@router.get("/audit")
def tenant_audit(
    params: PageParams = Depends(),
    action: str | None = None,
    resource_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: Ctx = Depends(require("core.audit.read")),
):
    q = select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_id)
    if action:
        q = q.where(AuditEvent.action.ilike(f"{action}%"))
    if resource_type:
        q = q.where(AuditEvent.resource_type == resource_type)
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    if date_from:
        q = q.where(AuditEvent.occurred_at >= date_from)
    if date_to:
        q = q.where(AuditEvent.occurred_at < date_to + timedelta(days=1))
    page = paginate(
        ctx.db,
        q,
        params,
        search_cols=(AuditEvent.action, AuditEvent.actor_email, AuditEvent.resource_type),
        default_sort=AuditEvent.occurred_at.desc(),
    )
    page["data"] = [
        {
            "id": a.id,
            "actor_email": a.actor_email,
            "actor_type": a.actor_type,
            "action": a.action,
            "resource_type": a.resource_type,
            "resource_id": a.resource_id,
            "before": a.before,
            "after": a.after,
            "occurred_at": a.occurred_at,
        }
        for a in page["data"]
    ]
    return page


def notify_members_with(
    db,
    tenant_id: uuid.UUID,
    perm: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    exclude: uuid.UUID | None = None,
) -> None:
    """Notify every active member holding ``perm``."""
    users = db.scalars(
        select(TenantMembership.user_id)
        .distinct()
        .join(MemberRole, MemberRole.membership_id == TenantMembership.id)
        .join(RolePermission, RolePermission.role_id == MemberRole.role_id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status == "active",
            RolePermission.permission_key == perm,
        )
    ).all()
    for u in users:
        if u != exclude:
            notify(db, tenant_id, u, title, body, link)
