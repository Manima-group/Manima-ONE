"""Sessions, password hashing, request context and route guards.

Identity: local email+password provider (dev/self-hosted) behind ``core.identity``.
ADR-0005's Cognito OIDC provider plugs into the same session issuance: the API
always issues its own opaque, server-side session cookie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from manima.core import entitlements as ent_engine
from manima.core.models import (
    MemberRole,
    PlatformRoleAssignment,
    PlatformUser,
    RolePermission,
    Tenant,
    TenantMembership,
    UserSession,
)
from manima.settings import get_settings
from manima.shared.db import get_db, set_tenant
from manima.shared.http import AppError

# ------------------------------------------------------------------ passwords
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def validate_password_strength(pw: str) -> None:
    if len(pw) < 10 or pw.lower() == pw or not any(c.isdigit() for c in pw):
        raise AppError(
            422,
            "WEAK_PASSWORD",
            "Password needs 10+ characters, an uppercase letter and a digit.",
            [{"field": "password", "issue": "weak"}],
        )


def sha256(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    t = secrets.token_urlsafe(32)
    return t, sha256(t)


# ------------------------------------------------------------------ sessions
def create_session(db: Session, user: PlatformUser, request: Request, tenant_id: uuid.UUID | None) -> str:
    token, digest = new_token()
    ip = request.client.host if request.client else ""
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=digest,
            active_tenant_id=tenant_id,
            expires_at=datetime.now(UTC) + timedelta(hours=get_settings().session_ttl_hours),
            ip_hash=sha256(ip)[:32],
            user_agent=(request.headers.get("user-agent") or "")[:300],
        )
    )
    return token


def set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name,
        token,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        max_age=s.session_ttl_hours * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(get_settings().session_cookie_name, path="/")


def revoke_user_sessions(db: Session, user_id: uuid.UUID, tenant_id: uuid.UUID | None = None) -> None:
    q = select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if tenant_id:
        q = q.where(UserSession.active_tenant_id == tenant_id)
    for s in db.scalars(q):
        s.revoked_at = datetime.now(UTC)


# ------------------------------------------------------------------ context
@dataclass
class Ctx:
    db: Session
    user: PlatformUser
    session: UserSession
    request_id: str | None
    platform_perms: set[str] = field(default_factory=set)
    tenant: Tenant | None = None
    membership: TenantMembership | None = None
    perms: set[str] = field(default_factory=set)
    _ent: ent_engine.TenantEntitlements | None = None

    @property
    def tenant_id(self) -> uuid.UUID:
        if self.tenant is None:
            raise AppError(400, "NO_ACTIVE_TENANT", "Select a company first.")
        return self.tenant.id

    @property
    def is_platform(self) -> bool:
        return bool(self.platform_perms)

    @property
    def ent(self) -> ent_engine.TenantEntitlements:
        if self._ent is None:
            assert self.tenant is not None
            self._ent = ent_engine.load(self.db, self.tenant)
        return self._ent

    def has(self, perm: str) -> bool:
        return perm in self.perms

    def check(self, perm: str) -> None:
        ent_engine.can(self.ent, self.perms, perm)

    def own_only(self, base: str) -> bool:
        """For ``crm.lead`` style bases: True when the user can only read their own records."""
        return f"{base}.read_all" not in self.perms


def platform_permissions(db: Session, user_id: uuid.UUID) -> set[str]:
    rows = db.execute(
        select(RolePermission.permission_key)
        .join(PlatformRoleAssignment, PlatformRoleAssignment.role_id == RolePermission.role_id)
        .where(PlatformRoleAssignment.user_id == user_id)
    )
    return {r[0] for r in rows}


def membership_permissions(db: Session, membership_id: uuid.UUID) -> set[str]:
    rows = db.execute(
        select(RolePermission.permission_key)
        .join(MemberRole, MemberRole.role_id == RolePermission.role_id)
        .where(MemberRole.membership_id == membership_id)
    )
    return {r[0] for r in rows}


def _load_ctx(request: Request, db: Session) -> Ctx:
    s = get_settings()
    token = request.cookies.get(s.session_cookie_name)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        raise AppError(401, "UNAUTHENTICATED", "Please sign in.")
    return load_ctx_from_token(db, token, getattr(request.state, "request_id", None))


def load_ctx_from_token(db: Session, token: str, request_id: str | None = None) -> Ctx:
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == sha256(token)))
    now = datetime.now(UTC)
    if sess is None or sess.revoked_at is not None or sess.expires_at < now:
        raise AppError(401, "SESSION_EXPIRED", "Your session has expired. Please sign in again.")
    user = db.get(PlatformUser, sess.user_id)
    if user is None or user.status != "active":
        raise AppError(401, "UNAUTHENTICATED", "Account disabled.")
    ctx = Ctx(db=db, user=user, session=sess, request_id=request_id)
    ctx.platform_perms = platform_permissions(db, user.id)
    if sess.active_tenant_id:
        m = db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == sess.active_tenant_id,
                TenantMembership.user_id == user.id,
                TenantMembership.status == "active",
            )
        )
        tenant = db.get(Tenant, sess.active_tenant_id)
        if m and tenant:
            ctx.tenant, ctx.membership = tenant, m
            ctx.perms = membership_permissions(db, m.id)
            set_tenant(db, tenant.id)
    return ctx


def current_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    return _load_ctx(request, db)


def tenant_ctx(ctx: Ctx = Depends(current_ctx)) -> Ctx:
    if ctx.tenant is None:
        raise AppError(400, "NO_ACTIVE_TENANT", "Select a company first.")
    if ctx.tenant.status == "closed":
        raise AppError(403, "TENANT_CLOSED", "This company account is closed.")
    return ctx


def require(*perms: str) -> Callable[..., Ctx]:
    """Route guard: user needs ANY of ``perms`` and the entitlement engine must allow it."""

    def dep(ctx: Ctx = Depends(tenant_ctx)) -> Ctx:
        last: AppError | None = None
        for p in perms:
            try:
                ctx.check(p)
                return ctx
            except AppError as e:
                if last is None or e.code != "PERMISSION_DENIED":
                    last = e
        assert last is not None
        raise last

    dep.__required_permissions__ = perms  # type: ignore[attr-defined]
    return dep


def require_platform(perm: str) -> Callable[..., Ctx]:
    def dep(ctx: Ctx = Depends(current_ctx)) -> Ctx:
        if perm not in ctx.platform_perms:
            raise AppError(403, "PERMISSION_DENIED", "Platform permission required.", feature=perm)
        # Platform staff never act inside a tenant's data scope through platform routes.
        set_tenant(ctx.db, None)
        ctx.tenant = None
        return ctx

    dep.__required_permissions__ = (perm,)  # type: ignore[attr-defined]
    return dep
