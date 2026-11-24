"""Release-blocking cross-tenant suite (TENANT_ISOLATION.md)."""

import uuid

from sqlalchemy import create_engine, text

from tests.conftest import APP_URL, OWNER_URL, gstin, signup


def _seed(app):
    owner, me = signup(app)
    owner.ok(
        "POST",
        "/api/v1/tenant/gst-registrations",
        json={"gstin": gstin("36", "AAACS1234F"), "legal_name": "Seller"},
    )
    acc = owner.ok("POST", "/api/v1/crm/accounts", json={"name": f"Acc {uuid.uuid4().hex[:4]}"})
    lead = owner.ok("POST", "/api/v1/crm/leads", json={"name": "Secret lead", "email": "secret@b.example"})
    item = owner.ok("POST", "/api/v1/catalog/items", json={"sku": "I1", "name": "Item", "price": "10"})
    q = owner.idem(
        "POST",
        "/api/v1/sales/quotations",
        json={"account_id": acc["id"], "lines": [{"item_id": item["id"], "qty": "1"}]},
    )
    inv = owner.idem(
        "POST",
        "/api/v1/billing/invoices",
        json={"account_id": acc["id"], "lines": [{"item_id": item["id"], "qty": "1"}]},
    )
    return {
        "api": owner,
        "tenant_id": me["active_tenant"]["id"],
        "account": acc,
        "lead": lead,
        "item": item,
        "quotation": q,
        "invoice": inv,
    }


def test_rest_cross_tenant_reads_return_404(app):
    a, b = _seed(app), _seed(app)
    api = a["api"]
    for url in (
        f"/api/v1/crm/leads/{b['lead']['id']}",
        f"/api/v1/crm/accounts/{b['account']['id']}",
        f"/api/v1/catalog/items/{b['item']['id']}",
        f"/api/v1/sales/quotations/{b['quotation']['id']}",
        f"/api/v1/billing/invoices/{b['invoice']['id']}",
    ):
        assert api.get(url).status_code == 404, url
    lists = api.ok("GET", "/api/v1/crm/leads?q=Secret")["data"]
    assert all(x["id"] != b["lead"]["id"] for x in lists)


def test_cross_tenant_writes_rejected(app):
    a, b = _seed(app), _seed(app)
    api = a["api"]
    r = api.post(
        "/api/v1/sales/quotations",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"account_id": b["account"]["id"], "lines": [{"item_id": a["item"]["id"], "qty": "1"}]},
    )
    assert r.status_code == 422
    r = api.post(
        "/api/v1/sales/quotations",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"account_id": a["account"]["id"], "lines": [{"item_id": b["item"]["id"], "qty": "1"}]},
    )
    assert r.status_code == 422
    assert api.patch(f"/api/v1/crm/leads/{b['lead']['id']}", json={"name": "pwned"}).status_code == 404
    assert api.delete(f"/api/v1/catalog/items/{b['item']['id']}").status_code == 404
    r = api.post(f"/api/v1/billing/invoices/{b['invoice']['id']}:issue", headers={"Idempotency-Key": "x1"})
    assert r.status_code == 404
    r = api.post(
        "/api/v1/billing/payments",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "account_id": a["account"]["id"],
            "amount": "1",
            "method": "cash",
            "allocations": [{"invoice_id": b["invoice"]["id"], "amount": "1"}],
        },
    )
    assert r.status_code == 422
    # tenant id in body/query is ignored: context only comes from the session
    r = api.ok("GET", f"/api/v1/crm/leads?tenant_id={b['tenant_id']}")
    assert all(x["id"] != b["lead"]["id"] for x in r["data"])


def _tenant_tables(conn):
    return [
        r[0]
        for r in conn.execute(
            text(
                "select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace "
                "join pg_attribute a on a.attrelid=c.oid and a.attname='tenant_id' "
                "where n.nspname='app' and c.relkind='r' and c.relname not in "
                "('tenants','tenant_memberships','invitations','roles','subscriptions','tenant_module_states',"
                "'tenant_feature_overrides','plan_changes')"
            )
        )
    ]


def test_rls_direct_sql(app):
    a, b = _seed(app), _seed(app)
    eng = create_engine(APP_URL)
    with eng.connect() as c:
        tables = _tenant_tables(c)
        assert "leads" in tables and "invoices" in tables
        c.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": a["tenant_id"]})
        for t in tables:
            n = c.execute(
                text(f"select count(*) from app.{t} where tenant_id = :b"), {"b": b["tenant_id"]}
            ).scalar()
            assert n == 0, f"{t} leaked tenant B rows"
        assert c.execute(text("select count(*) from app.leads")).scalar() >= 1
        # fail-closed when context unset
        c.execute(text("select set_config('app.tenant_id', '', false)"))
        for t in tables:
            assert c.execute(text(f"select count(*) from app.{t}")).scalar() == 0, (
                f"{t} visible without tenant"
            )
        # writing a row for another tenant is rejected by WITH CHECK
        c.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": a["tenant_id"]})
        try:
            c.execute(
                text(
                    "insert into app.leads (id, tenant_id, name, source, status, score, estimated_value, "
                    "version, is_sample) values (gen_random_uuid(), :b, 'x', 'manual', 'new', 0, 0, 1, false)"
                ),
                {"b": b["tenant_id"]},
            )
            raise AssertionError("cross-tenant insert should fail")
        except Exception as e:
            assert "row-level security" in str(e)
        c.rollback()
    eng.dispose()


def test_runtime_role_cannot_bypass_rls_via_session_settings(app):
    """No GUC the runtime role can set grants cross-tenant visibility (regression for app.bypass_rls)."""
    a, b = _seed(app), _seed(app)
    eng = create_engine(APP_URL)
    with eng.connect() as c:
        tables = _tenant_tables(c)
        c.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": a["tenant_id"]})
        for guc in ("app.bypass_rls", "row_security"):
            c.execute(text("select set_config(:g, 'on', false)"), {"g": guc})
        for t in tables:
            n = c.execute(
                text(f"select count(*) from app.{t} where tenant_id = :b"), {"b": b["tenant_id"]}
            ).scalar()
            assert n == 0, f"{t} leaked tenant B rows with bypass settings"
        rolbypass = c.execute(
            text("select rolbypassrls or rolsuper from pg_roles where rolname = current_user")
        ).scalar()
        assert rolbypass is False
    eng.dispose()


def test_every_tenant_table_has_forced_rls_and_append_only_grants(app):
    eng = create_engine(OWNER_URL)
    with eng.connect() as c:
        tables = _tenant_tables(c)
        rows = dict(
            c.execute(
                text(
                    "select relname, relrowsecurity and relforcerowsecurity from pg_class c "
                    "join pg_namespace n on n.oid=c.relnamespace where n.nspname='app'"
                )
            ).all()
        )
        missing = [t for t in tables if not rows.get(t)]
        assert not missing, f"tables without forced RLS: {missing}"
        for t in ("audit_events", "stock_ledger"):
            can_update = c.execute(
                text("select has_table_privilege('manima_app', :t, 'UPDATE')"), {"t": f"app.{t}"}
            ).scalar()
            assert can_update is False, f"{t} must be append-only"
    eng.dispose()


def test_composite_fk_blocks_cross_tenant_link_at_db_level(app):
    a, b = _seed(app), _seed(app)
    eng = create_engine(APP_URL)
    with eng.connect() as c:
        c.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": a["tenant_id"]})
        try:
            c.execute(
                text(
                    "insert into app.contacts (id, tenant_id, account_id, name, is_primary, version) "
                    "values (gen_random_uuid(), :a, :acc, 'x', false, 1)"
                ),
                {"a": a["tenant_id"], "acc": b["account"]["id"]},
            )
            raise AssertionError("composite FK should block")
        except Exception as e:
            assert "foreign key" in str(e).lower()
        c.rollback()
    eng.dispose()
