"""Authentication, session, signup, invitations acceptance, profile, notifications."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from manima.core import entitlements as ent_engine
from manima.core.audit import audit, emit
from manima.core.models import (
    Invitation,
    MemberRole,
    Notification,
    PlatformUser,
    Role,
    Tenant,
    TenantMembership,
    TenantSettings,
)
from manima.core.provisioning import provision_tenant
from manima.core.security import (
    Ctx,
    clear_session_cookie,
    create_session,
    current_ctx,
    hash_password,
    load_ctx_from_token,
    membership_permissions,
    set_session_cookie,
    sha256,
    tenant_ctx,
    validate_password_strength,
    verify_password,
)
from manima.shared import ratelimit
from manima.shared.db import get_db, set_tenant
from manima.shared.http import AppError, PageParams, paginate
from manima.shared.schemas import ORM

router = APIRouter(prefix="/api/v1", tags=["identity"])


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class SignupIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    state_code: str | None = Field(None, pattern=r"^[0-9]{2}$")


def _memberships(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(TenantMembership.user_id == user_id, TenantMembership.status == "active")
        .order_by(Tenant.legal_name)
    ).all()
    out = []
    for m, t in rows:
        roles = db.scalars(
            select(Role.name)
            .join(MemberRole, MemberRole.role_id == Role.id)
            .where(MemberRole.membership_id == m.id)
        ).all()
        out.append(
            {
                "tenant_id": t.id,
                "slug": t.slug,
                "name": t.legal_name,
                "status": t.status,
                "roles": list(roles),
            }
        )
    return out


def me_payload(ctx: Ctx) -> dict:
    db = ctx.db
    payload = {
        "user": {"id": ctx.user.id, "email": ctx.user.email, "name": ctx.user.name, "phone": ctx.user.phone},
        "platform_permissions": sorted(ctx.platform_perms),
        "memberships": _memberships(db, ctx.user.id),
        "active_tenant": None,
        "permissions": [],
        "capabilities": None,
    }
    if ctx.tenant is not None:
        s = db.get(TenantSettings, ctx.tenant.id)
        payload["active_tenant"] = {
            "id": ctx.tenant.id,
            "slug": ctx.tenant.slug,
            "name": ctx.tenant.legal_name,
            "status": ctx.tenant.status,
            "display_name": s.display_name if s else ctx.tenant.legal_name,
            "membership_id": ctx.membership.id if ctx.membership else None,
        }
        payload["permissions"] = sorted(ctx.perms)
        payload["capabilities"] = ent_engine.capabilities(ctx.ent, ctx.perms)
    return payload


def _first_tenant(db: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(
        select(TenantMembership.tenant_id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            Tenant.status != "closed",
        )
        .order_by(TenantMembership.joined_at)
        .limit(1)
    )


def _start(db: Session, request: Request, response: Response, user: PlatformUser, tenant_id) -> dict:
    token = create_session(db, user, request, tenant_id)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    set_session_cookie(response, token)
    return me_payload(load_ctx_from_token(db, token, getattr(request.state, "request_id", None)))


LOGIN_MAX_FAILURES = 10
LOGIN_MAX_PER_IP = 300
LOGIN_WINDOW_S = 15 * 60


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    ip = request.client.host if request.client else "-"
    # Brute-force guard: failed attempts per (email, ip) and per ip; a success clears the email counter.
    ratelimit.hit("login", f"{email}|{ip}", limit=LOGIN_MAX_FAILURES, window_s=LOGIN_WINDOW_S)
    ratelimit.hit("login-ip", ip, limit=LOGIN_MAX_PER_IP, window_s=LOGIN_WINDOW_S)
    user = db.scalar(select(PlatformUser).where(PlatformUser.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    ratelimit.reset("login", f"{email}|{ip}")
    if user.status != "active":
        raise AppError(403, "ACCOUNT_DISABLED", "This account is disabled.")
    return _start(db, request, response, user, _first_tenant(db, user.id))


@router.post("/auth/logout")
def logout(response: Response, ctx: Ctx = Depends(current_ctx)):
    ctx.session.revoked_at = datetime.now(UTC)
    ctx.db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    validate_password_strength(body.password)
    email = body.email.lower()
    if db.scalar(select(PlatformUser.id).where(PlatformUser.email == email)):
        raise AppError(409, "EMAIL_TAKEN", "An account with this email already exists. Sign in instead.")
    user = PlatformUser(email=email, name=body.name, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    tenant = provision_tenant(
        db,
        legal_name=body.company_name,
        owner=user,
        plan_key="growth",
        trial_days=14,
        state_code=body.state_code,
    )
    audit(db, None, "tenant.signup", "tenant", tenant.id, after={"slug": tenant.slug}, tenant_id=tenant.id)
    return _start(db, request, response, user, tenant.id)


@router.get("/me")
def me(ctx: Ctx = Depends(current_ctx)):
    return me_payload(ctx)


@router.get("/me/capabilities")
def my_capabilities(ctx: Ctx = Depends(tenant_ctx)):
    return ent_engine.capabilities(ctx.ent, ctx.perms)


class SwitchIn(BaseModel):
    tenant_id: uuid.UUID


@router.post("/session/switch-tenant")
def switch_tenant(body: SwitchIn, ctx: Ctx = Depends(current_ctx)):
    m = ctx.db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == body.tenant_id,
            TenantMembership.user_id == ctx.user.id,
            TenantMembership.status == "active",
        )
    )
    if m is None:
        raise AppError(404, "NOT_FOUND", "Company not found.")
    ctx.session.active_tenant_id = body.tenant_id
    ctx.db.commit()
    ctx.tenant = ctx.db.get(Tenant, body.tenant_id)
    ctx.membership, ctx._ent = m, None
    ctx.perms = membership_permissions(ctx.db, m.id)
    set_tenant(ctx.db, body.tenant_id)
    return me_payload(ctx)


class ProfileIn(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    phone: str | None = Field(None, max_length=20)
    title: str | None = Field(None, max_length=100)


@router.patch("/me/profile")
def update_profile(body: ProfileIn, ctx: Ctx = Depends(current_ctx)):
    if body.name is not None:
        ctx.user.name = body.name
    if body.phone is not None:
        ctx.user.phone = body.phone or None
    if body.title is not None and ctx.membership is not None:
        ctx.membership.title = body.title
    ctx.db.commit()
    return me_payload(ctx)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/me/password")
def change_password(body: PasswordIn, ctx: Ctx = Depends(current_ctx)):
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise AppError(
            422,
            "INVALID_CREDENTIALS",
            "Current password is incorrect.",
            [{"field": "current_password", "issue": "invalid"}],
        )
    validate_password_strength(body.new_password)
    ctx.user.password_hash = hash_password(body.new_password)
    ctx.db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- invitations (public side)
def _valid_invitation(db: Session, token: str) -> Invitation:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == sha256(token)))
    if inv is None or inv.accepted_at or inv.revoked_at or inv.expires_at < datetime.now(UTC):
        raise AppError(404, "INVITATION_INVALID", "This invitation is invalid or has expired.")
    return inv


@router.get("/invitations/{token}")
def invitation_preview(token: str, db: Session = Depends(get_db)):
    inv = _valid_invitation(db, token)
    t = db.get(Tenant, inv.tenant_id)
    existing = db.scalar(select(PlatformUser.id).where(PlatformUser.email == inv.email))
    return {
        "email": inv.email,
        "name": inv.name,
        "company": t.legal_name if t else None,
        "existing_user": existing is not None,
    }


class AcceptIn(BaseModel):
    token: str
    name: str | None = Field(None, max_length=120)
    password: str = Field(min_length=1, max_length=200)


@router.post("/invitations/accept")
def accept_invitation(body: AcceptIn, request: Request, response: Response, db: Session = Depends(get_db)):
    inv = _valid_invitation(db, body.token)
    user = db.scalar(select(PlatformUser).where(PlatformUser.email == inv.email))
    if user is None:
        validate_password_strength(body.password)
        user = PlatformUser(
            email=inv.email,
            name=body.name or inv.name or inv.email.split("@")[0],
            password_hash=hash_password(body.password),
        )
        db.add(user)
        db.flush()
    elif not verify_password(body.password, user.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "Enter your existing account password to join.")
    m = db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == inv.tenant_id, TenantMembership.user_id == user.id
        )
    )
    if m is None:
        m = TenantMembership(tenant_id=inv.tenant_id, user_id=user.id, invited_by=inv.invited_by)
        db.add(m)
    m.status, m.joined_at = "active", datetime.now(UTC)
    db.flush()
    db.execute(MemberRole.__table__.delete().where(MemberRole.membership_id == m.id))
    valid_roles = db.scalars(
        select(Role.id).where(Role.tenant_id == inv.tenant_id, Role.id.in_(inv.role_ids))
    ).all()
    for rid in valid_roles:
        db.add(MemberRole(membership_id=m.id, role_id=rid))
    inv.accepted_at = datetime.now(UTC)
    set_tenant(db, inv.tenant_id)
    audit(db, None, "member.joined", "membership", m.id, after={"email": user.email}, tenant_id=inv.tenant_id)
    emit(
        db,
        inv.tenant_id,
        "member.joined",
        "membership",
        m.id,
        {"user_id": str(user.id), "invited_by": str(inv.invited_by)},
    )
    return _start(db, request, response, user, inv.tenant_id)


# ---------------------------------------------------------------- notifications
class NotificationOut(ORM):
    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


@router.get("/notifications")
def list_notifications(params: PageParams = Depends(), unread: bool = False, ctx: Ctx = Depends(tenant_ctx)):
    q = select(Notification).where(
        Notification.tenant_id == ctx.tenant_id, Notification.user_id == ctx.user.id
    )
    if unread:
        q = q.where(Notification.read_at.is_(None))
    page = paginate(ctx.db, q, params, default_sort=Notification.created_at.desc(), schema=NotificationOut)
    page["unread"] = ctx.db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.tenant_id == ctx.tenant_id,
            Notification.user_id == ctx.user.id,
            Notification.read_at.is_(None),
        )
    )
    return page


@router.post("/notifications:read-all")
def read_all(ctx: Ctx = Depends(tenant_ctx)):
    ctx.db.execute(
        update(Notification)
        .where(
            Notification.tenant_id == ctx.tenant_id,
            Notification.user_id == ctx.user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    ctx.db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}:read")
def read_one(nid: uuid.UUID, ctx: Ctx = Depends(tenant_ctx)):
    n = ctx.db.get(Notification, nid)
    if n is None or n.user_id != ctx.user.id:
        raise AppError(404, "NOT_FOUND", "Notification not found.")
    n.read_at = datetime.now(UTC)
    ctx.db.commit()
    return {"ok": True}
