"""Five-check entitlement engine (FEATURE_ENTITLEMENT_ENGINE.md).

``can()`` is the single decision used by HTTP routes, jobs and consumers.
Feature keys are module keys (one platform feature per module) plus optional
sub-features registered in the ``features`` table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from manima.core.catalogue import MODULES_BY_KEY, module_of_permission
from manima.core.models import (
    Feature,
    Plan,
    PlanEntitlement,
    Subscription,
    Tenant,
    TenantFeatureOverride,
    TenantModuleState,
)
from manima.shared.http import AppError

READ_VERBS = ("read", "read_all", "read_own", "export")
ACTIVE_SUB = ("trialing", "active", "past_due", "grace")


def verb_of(perm: str) -> str:
    last = perm.rsplit(".", 1)[-1]
    if last in READ_VERBS:
        return "read"
    if last in ("create",):
        return "create"
    if last in ("send", "issue"):
        return "invoke"
    return last


@dataclass
class TenantEntitlements:
    tenant: Tenant
    plan: Plan | None
    plan_features: dict[str, dict] = field(default_factory=dict)
    overrides: dict[str, str] = field(default_factory=dict)
    module_states: dict[str, str] = field(default_factory=dict)
    features: dict[str, Feature] = field(default_factory=dict)

    def module_available(self, key: str) -> tuple[bool, str | None]:
        """Availability for writes: platform flag, plan/override, module state."""
        f = self.features.get(key)
        if f is None or not f.enabled or f.kill_switch:
            return False, "FEATURE_DISABLED_PLATFORM"
        if self.overrides.get(key) == "revoke":
            return False, "FEATURE_REVOKED"
        if key not in self.plan_features and self.overrides.get(key) != "grant":
            return False, "NOT_IN_PLAN"
        state = self.module_states.get(key, "disabled")
        if state != "enabled":
            return False, "MODULE_" + state.upper()
        return True, None

    def entitled(self, key: str) -> bool:
        if self.overrides.get(key) == "revoke":
            return False
        return key in self.plan_features or self.overrides.get(key) == "grant"


def load(db: Session, tenant: Tenant) -> TenantEntitlements:
    now = datetime.now(UTC)
    sub = db.scalar(
        select(Subscription)
        .where(Subscription.tenant_id == tenant.id, Subscription.status.in_(ACTIVE_SUB))
        .order_by(Subscription.created_at.desc())
    )
    if sub and sub.status == "trialing" and sub.trial_ends_at and sub.trial_ends_at < now:
        sub = None
    plan = db.get(Plan, sub.plan_id) if sub else None
    plan_features = (
        {
            pe.feature_key: pe.limits
            for pe in db.scalars(select(PlanEntitlement).where(PlanEntitlement.plan_id == plan.id))
        }
        if plan and plan.active
        else {}
    )
    overrides = {
        o.feature_key: o.effect
        for o in db.scalars(select(TenantFeatureOverride).where(TenantFeatureOverride.tenant_id == tenant.id))
        if o.expires_at is None or o.expires_at > now
    }
    states = {
        s.module_key: s.state
        for s in db.scalars(select(TenantModuleState).where(TenantModuleState.tenant_id == tenant.id))
    }
    features = {f.key: f for f in db.scalars(select(Feature))}
    return TenantEntitlements(tenant, plan, plan_features, overrides, states, features)


def deny(code: str, message: str, perm: str | None = None) -> AppError:
    hints = {
        "PERMISSION_DENIED": "ask_admin",
        "NOT_IN_PLAN": "upgrade_plan",
        "MODULE_DISABLED": "enable_module",
        "MODULE_READ_ONLY": "enable_module",
        "MODULE_DRAINING": "enable_module",
        "LIMIT_REACHED": "upgrade_plan",
    }
    extra = {"feature": perm} if perm else {}
    if code in hints:
        extra["action_hint"] = hints[code]
    return AppError(403, code, message, **extra)


def can(ent: TenantEntitlements, user_perms: set[str], perm: str) -> None:
    """Raise AppError(403) unless allowed. Order follows the documented precedence."""
    tenant = ent.tenant
    verb = verb_of(perm)
    if tenant.status == "closed":
        raise deny("TENANT_CLOSED", "This company account is closed.")
    if tenant.status in ("suspended", "closing") and verb != "read":
        raise deny("TENANT_INACTIVE", "This company account is suspended; data is read-only.")
    module = module_of_permission(perm)
    if verb == "read" or MODULES_BY_KEY[module].kind == "core":
        # History is always the customer's: reads only need the role permission.
        if perm not in user_perms:
            raise deny("PERMISSION_DENIED", "You do not have permission for this action.", perm)
        return
    ok, code = ent.module_available(module)
    if not ok:
        name = MODULES_BY_KEY[module].name
        messages = {
            "FEATURE_DISABLED_PLATFORM": f"{name} is temporarily unavailable.",
            "NOT_IN_PLAN": f"{name} is not included in your plan.",
            "FEATURE_REVOKED": f"{name} has been revoked for this company.",
        }
        raise deny(
            code or "MODULE_DISABLED",
            messages.get(
                code or "", f"{name} is {(code or '').split('_', 1)[-1].lower().replace('_', ' ')}."
            ),
            perm,
        )
    if perm not in user_perms:
        raise deny("PERMISSION_DENIED", "You do not have permission for this action.", perm)


def capabilities(ent: TenantEntitlements, user_perms: set[str]) -> dict:
    """UI hints only; backend still enforces on every request."""
    modules = {}
    for key, m in MODULES_BY_KEY.items():
        if m.kind == "core":
            continue
        ok, code = ent.module_available(key)
        modules[key] = {
            "state": ent.module_states.get(key, "disabled"),
            "entitled": ent.entitled(key),
            "writable": ok,
            "reason": code,
        }
    return {"modules": modules, "permissions": sorted(user_perms)}


def any_tenant_id(value: uuid.UUID | None) -> uuid.UUID:
    if value is None:
        raise AppError(400, "NO_ACTIVE_TENANT", "Select a company first.")
    return value


__all__ = ["can", "load", "capabilities", "verb_of", "TenantEntitlements", "module_of_permission"]
