"""Route audit (API_STANDARDS §3, PLT-04): every /api/v1 route declares a permission guard.

Routes without a guard must be listed below with the reason they are safe. A new unguarded
route fails this test until it is either guarded or consciously added to the allow-list.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from manima.catalogue_check import all_declared_permissions
from manima.main import create_app

# Self-service / pre-auth routes: scoped to the caller's own identity, never to tenant business data.
UNGUARDED_ALLOWED = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/signup"),
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/me/capabilities"),
    ("PATCH", "/api/v1/me/profile"),
    ("POST", "/api/v1/me/password"),
    ("POST", "/api/v1/session/switch-tenant"),  # membership checked in handler
    ("GET", "/api/v1/invitations/{token}"),  # token-hash lookup
    ("POST", "/api/v1/invitations/accept"),
    ("GET", "/api/v1/notifications"),  # rows filtered to the caller's user_id
    ("POST", "/api/v1/notifications/{nid}:read"),
    ("POST", "/api/v1/notifications:read-all"),
    ("GET", "/api/v1/gst/states"),  # static reference data
    ("GET", "/api/v1/gst/validate-gstin"),  # pure function
    # Tenant members (tenant_ctx): reference data / pickers every role needs to fill forms.
    ("GET", "/api/v1/billing/note-reasons"),  # static list
    ("GET", "/api/v1/catalog/units"),  # static list
    ("GET", "/api/v1/tenant/gst-registrations"),  # company's own GSTINs for document forms
    ("GET", "/api/v1/tenant/members/options"),  # names only, for owner/assignee pickers
    ("GET", "/api/v1/tenant/modules"),  # module on/off states for UI hints
    ("GET", "/api/v1/reports/dashboard"),  # each section gated by ctx.has(...) in the handler
}


def _guards(dependant) -> list[tuple[str, ...]]:
    out = []
    stack = [dependant]
    while stack:
        d = stack.pop()
        perms = getattr(d.call, "__required_permissions__", None)
        if perms:
            out.append(tuple(perms))
        stack.extend(d.dependencies)
    return out


def _walk(routes):
    # FastAPI >= 0.16x wraps included routers lazily; descend into them (prefixes live on the routers).
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _walk(inner.routes)
        elif isinstance(r, APIRoute):
            yield r


def _routes():
    found = list(_walk(create_app().router.routes))
    assert len(found) > 100, "route discovery broke: too few routes found"
    for r in found:
        if r.path.startswith("/api/v1"):
            for m in sorted(r.methods - {"HEAD"}):
                yield m, r.path, r


def test_every_route_is_guarded_or_explicitly_allowed():
    unguarded = sorted((m, p) for m, p, r in _routes() if not _guards(r.dependant))
    unexpected = [x for x in unguarded if x not in UNGUARDED_ALLOWED]
    assert not unexpected, f"routes without a permission guard: {unexpected}"
    stale = sorted(UNGUARDED_ALLOWED - set(unguarded))
    assert not stale, f"allow-list entries that no longer exist or are now guarded: {stale}"


def test_guards_reference_declared_permissions():
    declared = all_declared_permissions()
    bad = sorted(
        {
            (m, p, perm)
            for m, p, r in _routes()
            for g in _guards(r.dependant)
            for perm in g
            if perm not in declared
        }
    )
    assert not bad, f"guards naming undeclared permissions: {bad}"
