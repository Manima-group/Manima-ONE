"""Registry sync, tenant provisioning (industry pack) and module lifecycle."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from manima.core.audit import audit, emit
from manima.core.catalogue import (
    DEFAULT_ROLES,
    MODULES,
    MODULES_BY_KEY,
    PLATFORM_PERMISSIONS,
    PLATFORM_ROLES,
    TOGGLEABLE_MODULES,
)
from manima.core.models import (
    Feature,
    MemberRole,
    Module,
    Permission,
    Plan,
    PlanEntitlement,
    PlatformUser,
    Role,
    RolePermission,
    Subscription,
    Tenant,
    TenantMembership,
    TenantModuleState,
    TenantSettings,
)
from manima.shared.db import set_tenant
from manima.shared.http import AppError

# Module lifecycle hooks registered by business modules: key -> fn(db, tenant_id)
ON_ENABLE: dict[str, list[Callable[[Session, uuid.UUID], None]]] = {}


def on_enable(module_key: str):
    def deco(fn):
        ON_ENABLE.setdefault(module_key, []).append(fn)
        return fn

    return deco


DEFAULT_PLANS = [
    (
        "starter",
        "Starter",
        "CRM, sales, GST invoicing and payments",
        Decimal("999.00"),
        5,
        ["crm", "catalog", "compliance_gst", "sales", "invoicing", "payments", "reports"],
    ),
    (
        "growth",
        "Growth",
        "Everything in Starter plus inventory and procurement",
        Decimal("2999.00"),
        25,
        TOGGLEABLE_MODULES,
    ),
    (
        "enterprise",
        "Enterprise",
        "All modules, unlimited users",
        Decimal("7999.00"),
        None,
        TOGGLEABLE_MODULES,
    ),
]


def sync_registry(db: Session) -> None:
    """Idempotent upsert of modules, features, permissions, platform roles and default plans."""
    for m in MODULES:
        row = db.get(Module, m.key)
        if row is None:
            row = Module(key=m.key, platform_state="available")
            db.add(row)
        row.version, row.name, row.description, row.kind = m.version, m.name, m.description, m.kind
        row.depends_on = list(m.depends_on)
        row.manifest = {"permissions": list(m.permissions), "depends_on": list(m.depends_on)}
        db.flush()
        if m.kind != "core" and db.get(Feature, m.key) is None:
            db.add(Feature(key=m.key, module_key=m.key, name=m.name))
        for k, desc in m.permissions.items():
            p = db.get(Permission, k) or Permission(key=k)
            p.module_key, p.description, p.scope, p.sensitive = m.key, desc, "tenant", k in m.sensitive
            db.merge(p)
    for k, desc in PLATFORM_PERMISSIONS.items():
        db.merge(
            Permission(key=k, module_key="platform", scope="platform", description=desc, sensitive=False)
        )
    db.flush()
    for key, (name, perms) in PLATFORM_ROLES.items():
        role = db.scalar(select(Role).where(Role.tenant_id.is_(None), Role.key == key))
        if role is None:
            role = Role(key=key, name=name, is_system=True, tenant_id=None)
            db.add(role)
            db.flush()
        existing = set(
            db.scalars(select(RolePermission.permission_key).where(RolePermission.role_id == role.id))
        )
        for p in perms:
            if p not in existing:
                db.add(RolePermission(role_id=role.id, permission_key=p))
    if db.scalar(select(Plan).limit(1)) is None:
        for key, name, desc, price, max_users, mods in DEFAULT_PLANS:
            plan = Plan(key=key, name=name, description=desc, price_monthly=price, max_users=max_users)
            db.add(plan)
            db.flush()
            for mk in mods:
                db.add(PlanEntitlement(plan_id=plan.id, feature_key=mk, limits={}))
    db.flush()


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
    return s or "company"


def unique_slug(db: Session, base: str) -> str:
    slug, i = base, 1
    while db.scalar(select(Tenant.id).where(Tenant.slug == slug)):
        i += 1
        slug = f"{base}-{i}"
    return slug


def create_tenant_roles(db: Session, tenant_id: uuid.UUID) -> dict[str, Role]:
    roles = {}
    for key, (name, desc, perms) in DEFAULT_ROLES.items():
        r = Role(tenant_id=tenant_id, key=key, name=name, description=desc, is_system=True)
        db.add(r)
        db.flush()
        for p in sorted(set(perms)):
            db.add(RolePermission(role_id=r.id, permission_key=p))
        roles[key] = r
    return roles


def topo_order(keys: list[str]) -> list[str]:
    out: list[str] = []

    def visit(k: str, stack: tuple = ()):
        if k in out:
            return
        if k in stack:
            raise ValueError(f"module dependency cycle at {k}")
        for d in MODULES_BY_KEY[k].depends_on:
            if d in keys:
                visit(d, stack + (k,))
        out.append(k)

    for k in keys:
        visit(k)
    return out


def provision_tenant(
    db: Session,
    *,
    legal_name: str,
    owner: PlatformUser,
    plan_key: str = "growth",
    actor: PlatformUser | None = None,
    trial_days: int | None = 14,
    slug: str | None = None,
    state_code: str | None = None,
) -> Tenant:
    plan = db.scalar(select(Plan).where(Plan.key == plan_key, Plan.active.is_(True)))
    if plan is None:
        raise AppError(
            422, "PLAN_NOT_FOUND", "Unknown or inactive plan.", [{"field": "plan_key", "issue": "invalid"}]
        )
    tenant = Tenant(slug=unique_slug(db, slugify(slug or legal_name)), legal_name=legal_name)
    db.add(tenant)
    db.flush()
    set_tenant(db, tenant.id)
    db.add(
        TenantSettings(tenant_id=tenant.id, display_name=legal_name, email=owner.email, state_code=state_code)
    )
    roles = create_tenant_roles(db, tenant.id)
    m = TenantMembership(
        tenant_id=tenant.id,
        user_id=owner.id,
        status="active",
        joined_at=datetime.now(UTC),
        title="Owner",
        invited_by=actor.id if actor else None,
    )
    db.add(m)
    db.flush()
    db.add(MemberRole(membership_id=m.id, role_id=roles["owner"].id))
    now = datetime.now(UTC)
    db.add(
        Subscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status="trialing" if trial_days else "active",
            trial_ends_at=now + timedelta(days=trial_days) if trial_days else None,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
    )
    entitled = [
        pe.feature_key for pe in db.scalars(select(PlanEntitlement).where(PlanEntitlement.plan_id == plan.id))
    ]
    for key in TOGGLEABLE_MODULES:
        db.add(TenantModuleState(tenant_id=tenant.id, module_key=key, state="disabled", reason="provisioned"))
    db.flush()
    for key in topo_order([k for k in TOGGLEABLE_MODULES if k in entitled]):
        st = db.get(TenantModuleState, (tenant.id, key))
        st.state, st.reason, st.changed_by = (
            "enabled",
            "industry pack: distribution",
            actor.id if actor else owner.id,
        )
        for hook in ON_ENABLE.get(key, []):
            hook(db, tenant.id)
    db.flush()
    emit(db, tenant.id, "tenant.created", "tenant", tenant.id, {"slug": tenant.slug, "plan": plan.key})
    return tenant


TRANSITIONS = {
    ("disabled", "enabled"),
    ("enabled", "draining"),
    ("draining", "read_only"),
    ("read_only", "disabled"),
    ("read_only", "enabled"),
    ("draining", "enabled"),
}


def change_module_state(
    db: Session, ctx, tenant: Tenant, key: str, target: str, reason: str, ent
) -> TenantModuleState:
    if key not in TOGGLEABLE_MODULES:
        raise AppError(404, "NOT_FOUND", "Module not found.")
    if target not in ("enabled", "read_only", "disabled"):
        raise AppError(422, "INVALID_TARGET_STATE", "Target must be enabled, read_only or disabled.")
    st = db.get(TenantModuleState, (tenant.id, key))
    if st is None:
        st = TenantModuleState(tenant_id=tenant.id, module_key=key, state="disabled")
        db.add(st)
    states = {
        s.module_key: s.state
        for s in db.scalars(select(TenantModuleState).where(TenantModuleState.tenant_id == tenant.id))
    }
    if target == "enabled":
        mod = db.get(Module, key)
        if mod is None or mod.platform_state != "available":
            raise AppError(409, "MODULE_NOT_AVAILABLE", "This module is not available on the platform.")
        if not ent.entitled(key):
            raise AppError(
                403, "NOT_IN_PLAN", "This module is not included in your plan.", action_hint="upgrade_plan"
            )
        missing = [d for d in MODULES_BY_KEY[key].depends_on if states.get(d) != "enabled"]
        if missing:
            raise AppError(
                409, "DEPENDENCY_DISABLED", f"Enable {', '.join(missing)} first.", dependencies=missing
            )
        path = [st.state, "enabled"]
    else:
        dependants = [
            m.key for m in MODULES if key in m.depends_on and states.get(m.key) in ("enabled", "draining")
        ]
        if dependants:
            raise AppError(
                409, "HAS_DEPENDANTS", f"Disable {', '.join(dependants)} first.", dependants=dependants
            )
        order = ["enabled", "draining", "read_only", "disabled"]
        if st.state not in order or order.index(target) < order.index(st.state):
            raise AppError(409, "INVALID_TRANSITION", f"Cannot move from {st.state} to {target}.")
        path = order[order.index(st.state) : order.index(target) + 1]
    if len(path) < 2 or path[0] == path[-1]:
        return st
    for frm, to in zip(path, path[1:], strict=False):
        if (frm, to) not in TRANSITIONS:
            raise AppError(409, "INVALID_TRANSITION", f"Cannot move from {frm} to {to}.")
        audit(
            db,
            ctx,
            "module.state_changed",
            "module",
            key,
            before={"state": frm},
            after={"state": to, "reason": reason},
            tenant_id=tenant.id,
        )
    st.state, st.reason, st.changed_by, st.changed_at = target, reason, ctx.user.id, datetime.now(UTC)
    if target == "enabled":
        for hook in ON_ENABLE.get(key, []):
            hook(db, tenant.id)
    emit(db, tenant.id, "module.state_changed", "module", key, {"module": key, "state": target})
    return st
