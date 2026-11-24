from tests.conftest import add_member, signup, super_admin


def _tenant_id(api):
    return api.ok("GET", "/api/v1/me")["active_tenant"]["id"]


def test_module_disable_blocks_writes_keeps_reads(app, company):
    owner = company["owner"]
    # procurement depends on inventory: disabling inventory first must be refused
    r = owner.patch("/api/v1/tenant/modules/inventory", json={"state": "disabled", "reason": "test"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "HAS_DEPENDANTS"
    owner.ok("PATCH", "/api/v1/tenant/modules/procurement", json={"state": "read_only", "reason": "pause"})
    assert owner.get("/api/v1/procurement/vendors").status_code == 200
    r = owner.post("/api/v1/procurement/vendors", json={"name": "V"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "MODULE_READ_ONLY"
    owner.ok("PATCH", "/api/v1/tenant/modules/procurement", json={"state": "disabled", "reason": "turn off"})
    assert (
        owner.post("/api/v1/procurement/vendors", json={"name": "V"}).json()["error"]["code"]
        == "MODULE_DISABLED"
    )
    assert owner.get("/api/v1/procurement/vendors").status_code == 200  # history stays readable
    owner.ok("PATCH", "/api/v1/tenant/modules/procurement", json={"state": "enabled", "reason": "back on"})
    owner.ok("POST", "/api/v1/procurement/vendors", json={"name": "V"})
    audit = owner.ok("GET", "/api/v1/tenant/audit?action=module.state_changed")["data"]
    assert len(audit) >= 4  # every transition audited


def test_enable_requires_dependencies(app):
    owner, _ = signup(app)
    owner.ok("PATCH", "/api/v1/tenant/modules/payments", json={"state": "disabled", "reason": "test"})
    owner.ok("PATCH", "/api/v1/tenant/modules/invoicing", json={"state": "disabled", "reason": "test"})
    r = owner.patch("/api/v1/tenant/modules/payments", json={"state": "enabled", "reason": "test"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DEPENDENCY_DISABLED"


def test_kill_switch_and_overrides(app):
    sa = super_admin(app)
    owner, _ = signup(app)
    tid = _tenant_id(owner)
    try:
        sa.ok("PATCH", "/api/v1/platform/features/crm", json={"kill_switch": True})
        r = owner.post("/api/v1/crm/leads", json={"name": "x"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "FEATURE_DISABLED_PLATFORM"
        assert owner.get("/api/v1/crm/leads").status_code == 200
    finally:
        sa.ok("PATCH", "/api/v1/platform/features/crm", json={"kill_switch": False})
    owner.ok("POST", "/api/v1/crm/leads", json={"name": "x"})
    sa.ok("PUT", f"/api/v1/platform/tenants/{tid}/features/crm", json={"effect": "revoke", "reason": "abuse"})
    assert owner.post("/api/v1/crm/leads", json={"name": "x"}).json()["error"]["code"] == "FEATURE_REVOKED"
    sa.ok("DELETE", f"/api/v1/platform/tenants/{tid}/features/crm")
    owner.ok("POST", "/api/v1/crm/leads", json={"name": "x"})


def test_plan_without_inventory(app):
    sa = super_admin(app)
    owner, _ = signup(app)
    tid = _tenant_id(owner)
    sa.ok(
        "POST",
        f"/api/v1/platform/tenants/{tid}/subscription",
        json={"plan_key": "starter", "status": "active"},
    )
    r = owner.post("/api/v1/inventory/warehouses", json={"name": "W2", "code": "W2"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "NOT_IN_PLAN"
    assert (
        owner.get("/api/v1/inventory/warehouses").status_code == 200
    )  # plan downgrade keeps history readable
    sa.ok(
        "PUT",
        f"/api/v1/platform/tenants/{tid}/features/inventory",
        json={"effect": "grant", "reason": "trial"},
    )
    owner.ok("POST", "/api/v1/inventory/warehouses", json={"name": "W2", "code": "W2"})


def test_seat_limit(app):
    sa = super_admin(app)
    owner, _ = signup(app)
    tid = _tenant_id(owner)
    plan = sa.ok(
        "POST",
        "/api/v1/platform/plans",
        json={
            "key": f"tiny{tid[:6]}".replace("-", ""),
            "name": "Tiny",
            "price_monthly": "1",
            "max_users": 2,
            "modules": ["crm"],
        },
    )
    sa.ok(
        "POST",
        f"/api/v1/platform/tenants/{tid}/subscription",
        json={"plan_key": plan["key"], "status": "active"},
    )
    add_member(app, owner, "viewer")
    rid = owner.ok("GET", "/api/v1/tenant/roles")[0]["id"]
    r = owner.post("/api/v1/tenant/invitations", json={"email": "third@example.com", "role_ids": [rid]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "LIMIT_REACHED"


def test_suspended_tenant_is_read_only(app):
    sa = super_admin(app)
    owner, _ = signup(app)
    tid = _tenant_id(owner)
    sa.ok("POST", f"/api/v1/platform/tenants/{tid}:suspend", json={"reason": "non-payment"})
    assert owner.get("/api/v1/crm/leads").status_code == 200
    assert owner.post("/api/v1/crm/leads", json={"name": "x"}).json()["error"]["code"] == "TENANT_INACTIVE"
    sa.ok("POST", f"/api/v1/platform/tenants/{tid}:reactivate")
    owner.ok("POST", "/api/v1/crm/leads", json={"name": "x"})


def test_platform_routes_need_platform_role(app):
    owner, _ = signup(app)
    r = owner.get("/api/v1/platform/tenants")
    assert r.status_code == 403
