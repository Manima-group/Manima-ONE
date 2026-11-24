import uuid

from tests.conftest import PASSWORD, Api, add_member, signup


def test_signup_me_logout_login(app):
    a, me = signup(app, "Acme Traders")
    assert me["active_tenant"]["name"] == "Acme Traders"
    assert "core.member.manage" in me["permissions"]
    caps = me["capabilities"]["modules"]
    assert caps["inventory"]["writable"] is True  # growth trial includes inventory
    a.ok("POST", "/api/v1/auth/logout")
    assert a.get("/api/v1/me").status_code == 401
    b = Api(app)
    r = b.post("/api/v1/auth/login", json={"email": me["email"], "password": "wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    b.ok("POST", "/api/v1/auth/login", json={"email": me["email"], "password": PASSWORD})
    assert b.ok("GET", "/api/v1/me")["user"]["email"] == me["email"]


def test_csrf_header_required_for_writes(app):
    a, _ = signup(app)
    r = a.c.post("/api/v1/crm/leads", json={"name": "x"}, headers={"X-Requested-With": ""})
    assert r.status_code == 400 and r.json()["error"]["code"] == "CSRF_HEADER_MISSING"


def test_weak_password_and_duplicate_email(app):
    a = Api(app)
    r = a.post(
        "/api/v1/signup",
        json={"company_name": "X Co", "name": "Xy", "email": "weak@example.com", "password": "weakpassword"},
    )
    assert r.status_code == 422
    _, me = signup(app)
    r = a.post(
        "/api/v1/signup",
        json={"company_name": "Y Co", "name": "Yy", "email": me["email"], "password": PASSWORD},
    )
    assert r.status_code == 409


def test_role_permissions_enforced(app):
    owner, _ = signup(app)
    exec_ = add_member(app, owner, "sales_exec")
    viewer = add_member(app, owner, "viewer")
    accounts = add_member(app, owner, "accounts")
    # viewer: read yes, write no
    assert viewer.get("/api/v1/crm/leads").status_code == 200
    r = viewer.post("/api/v1/crm/leads", json={"name": "Nope"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"
    # accounts cannot create leads but can read invoices
    assert accounts.post("/api/v1/crm/leads", json={"name": "Nope"}).status_code == 403
    assert accounts.get("/api/v1/billing/invoices").status_code == 200
    # sales exec cannot manage employees or issue invoices
    assert exec_.get("/api/v1/tenant/invitations").status_code == 403
    assert (
        exec_.post(
            f"/api/v1/billing/invoices/{uuid.uuid4()}:issue", headers={"Idempotency-Key": "k"}
        ).status_code
        == 403
    )


def test_sales_exec_sees_only_own_leads(app):
    owner, _ = signup(app)
    exec_ = add_member(app, owner, "sales_exec")
    mine = exec_.ok("POST", "/api/v1/crm/leads", json={"name": "Mine"})
    theirs = owner.ok("POST", "/api/v1/crm/leads", json={"name": "Owner's lead"})
    names = {x["name"] for x in exec_.ok("GET", "/api/v1/crm/leads")["data"]}
    assert names == {"Mine"}
    assert exec_.get(f"/api/v1/crm/leads/{theirs['id']}").status_code == 404
    assert exec_.ok("GET", f"/api/v1/crm/leads/{mine['id']}")["name"] == "Mine"
    assert len(owner.ok("GET", "/api/v1/crm/leads")["data"]) == 2


def test_custom_role_and_member_role_change_revokes_sessions(app):
    owner, _ = signup(app)
    viewer = add_member(app, owner, "viewer")
    role = owner.ok(
        "POST",
        "/api/v1/tenant/roles",
        json={"name": "Lead entry", "permissions": ["crm.lead.read_own", "crm.lead.create"]},
    )
    members = owner.ok("GET", "/api/v1/tenant/members")["data"]
    vm = next(m for m in members if m["roles"][0]["key"] == "viewer")
    owner.ok("PATCH", f"/api/v1/tenant/members/{vm['id']}", json={"role_ids": [role["id"]]})
    assert viewer.get("/api/v1/me").status_code == 401  # session revoked on role change
    bad = owner.post("/api/v1/tenant/roles", json={"name": "Bad", "permissions": ["platform.tenant.create"]})
    assert bad.status_code == 422  # platform permissions never assignable in a tenant


def test_last_owner_protected(app):
    owner, _ = signup(app)
    me = owner.ok("GET", "/api/v1/me")
    members = owner.ok("GET", "/api/v1/tenant/members")["data"]
    mid = members[0]["id"]
    viewer_role = next(r["id"] for r in owner.ok("GET", "/api/v1/tenant/roles") if r["key"] == "viewer")
    r = owner.patch(f"/api/v1/tenant/members/{mid}", json={"role_ids": [viewer_role]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_OWNER"
    assert me["active_tenant"]


def test_switch_tenant_between_memberships(app):
    owner_a, _ = signup(app, "Alpha")
    owner_b, me_b = signup(app, "Beta")
    # invite Beta's owner into Alpha
    rid = next(r["id"] for r in owner_a.ok("GET", "/api/v1/tenant/roles") if r["key"] == "viewer")
    inv = owner_a.ok("POST", "/api/v1/tenant/invitations", json={"email": me_b["email"], "role_ids": [rid]})
    token = inv["accept_path"].rsplit("/", 1)[-1]
    owner_b.ok("POST", "/api/v1/invitations/accept", json={"token": token, "password": PASSWORD})
    me = owner_b.ok("GET", "/api/v1/me")
    assert {m["name"] for m in me["memberships"]} == {"Alpha", "Beta"}
    beta_id = next(m["tenant_id"] for m in me["memberships"] if m["name"] == "Beta")
    owner_b.ok("POST", "/api/v1/crm/leads", json={"name": "Beta lead"}) if me["active_tenant"][
        "name"
    ] == "Beta" else None
    me2 = owner_b.ok("POST", "/api/v1/session/switch-tenant", json={"tenant_id": beta_id})
    assert me2["active_tenant"]["name"] == "Beta" and "core.member.manage" in me2["permissions"]
    r = owner_b.post("/api/v1/session/switch-tenant", json={"tenant_id": str(uuid.uuid4())})
    assert r.status_code == 404


def test_profile_and_password_change(app):
    a, me = signup(app)
    a.ok("PATCH", "/api/v1/me/profile", json={"name": "New Name", "phone": "+911234567890"})
    assert a.ok("GET", "/api/v1/me")["user"]["name"] == "New Name"
    assert (
        a.post(
            "/api/v1/me/password", json={"current_password": "x", "new_password": "Another@12345"}
        ).status_code
        == 422
    )
    a.ok("POST", "/api/v1/me/password", json={"current_password": PASSWORD, "new_password": "Another@12345"})
    b = Api(app)
    b.ok("POST", "/api/v1/auth/login", json={"email": me["email"], "password": "Another@12345"})


def test_login_brute_force_is_rate_limited(app):
    import uuid as _uuid

    from fastapi.testclient import TestClient

    client = TestClient(app)
    email = f"rl-{_uuid.uuid4().hex[:8]}@example.com"
    headers = {"X-Requested-With": "manima"}
    codes = [
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"}, headers=headers)
        for _ in range(11)
    ]
    assert [r.status_code for r in codes[:10]] == [401] * 10
    assert codes[10].status_code == 429
    assert codes[10].json()["error"]["code"] == "RATE_LIMITED"
    assert int(codes[10].headers["Retry-After"]) > 0
