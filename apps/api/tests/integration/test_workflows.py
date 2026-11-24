"""End-to-end business workflows through the HTTP API."""

import uuid
from decimal import Decimal as D

from sqlalchemy import select

from tests.conftest import add_member, signup, super_admin


def stock_of(api, item_id):
    return D(api.ok("GET", f"/api/v1/inventory/stock/{item_id}")["warehouses"][0]["on_hand"])


def test_order_to_cash(app, company):
    o, cust, widget, svc = company["owner"], company["customer"], company["widget"], company["service"]
    # quotation (intra-state: CGST+SGST)
    q = o.idem(
        "POST",
        "/api/v1/sales/quotations",
        json={
            "account_id": cust["id"],
            "lines": [{"item_id": widget["id"], "qty": "2"}, {"item_id": svc["id"], "qty": "1"}],
        },
    )
    assert q["status"] == "draft" and q["number"] is None
    assert (
        D(q["taxable_total"]) == D("2500.00")
        and D(q["cgst_total"]) == D("225.00")
        and D(q["igst_total"]) == 0
    )
    assert D(q["grand_total"]) == D("2950.00")
    sent = o.ok("POST", f"/api/v1/sales/quotations/{q['id']}:send")
    assert sent["status"] == "sent" and sent["number"].startswith("QT/")
    # edit after send => new revision, old superseded
    rev = o.ok(
        "PATCH",
        f"/api/v1/sales/quotations/{q['id']}",
        json={"account_id": cust["id"], "lines": [{"item_id": widget["id"], "qty": "3"}]},
    )
    assert rev["revision"] == 2 and rev["id"] != q["id"] and rev["number"] == sent["number"]
    assert o.ok("GET", f"/api/v1/sales/quotations/{q['id']}")["status"] == "superseded"
    o.ok("POST", f"/api/v1/sales/quotations/{rev['id']}:send")
    o.ok("POST", f"/api/v1/sales/quotations/{rev['id']}:accept")
    so = o.idem("POST", f"/api/v1/sales/quotations/{rev['id']}:convert")
    assert so["status"] == "draft" and so["quotation_id"] == rev["id"] and len(so["lines"]) == 1
    # confirm reserves, deliver moves stock
    o.ok("POST", f"/api/v1/sales/orders/{so['id']}:confirm")
    wh_stock = o.ok("GET", f"/api/v1/inventory/stock/{widget['id']}")["warehouses"][0]
    assert D(wh_stock["reserved"]) == D("3") and D(wh_stock["on_hand"]) == D("10")
    o.ok("POST", f"/api/v1/sales/orders/{so['id']}:deliver")
    wh_stock = o.ok("GET", f"/api/v1/inventory/stock/{widget['id']}")["warehouses"][0]
    assert D(wh_stock["reserved"]) == 0 and D(wh_stock["on_hand"]) == D("7")
    # invoice from order, issue
    inv = o.idem("POST", "/api/v1/billing/invoices", json={"sales_order_id": so["id"]})
    assert (
        inv["document_status"] == "draft" and inv["number"] is None and D(inv["grand_total"]) == D("3540.00")
    )
    issued = o.idem("POST", f"/api/v1/billing/invoices/{inv['id']}:issue")
    assert issued["document_status"] == "issued" and issued["number"].startswith("INV/")
    assert len(issued["number"]) <= 16 and issued["payment_status"] == "unpaid"
    assert o.ok("GET", f"/api/v1/sales/orders/{so['id']}")["invoice_id"] == inv["id"]
    # partial payment then the rest
    p1 = o.idem(
        "POST",
        "/api/v1/billing/payments",
        json={
            "account_id": cust["id"],
            "amount": "1000",
            "method": "upi",
            "allocations": [{"invoice_id": inv["id"], "amount": "1000"}],
        },
    )
    assert D(p1["unallocated"]) == 0
    got = o.ok("GET", f"/api/v1/billing/invoices/{inv['id']}")
    assert got["payment_status"] == "partially_paid" and D(got["amount_due"]) == D("2540.00")
    # credit note for one returned widget reduces the balance
    cn = o.idem(
        "POST",
        "/api/v1/billing/credit-notes",
        json={
            "invoice_id": inv["id"],
            "reason": "sales_return",
            "lines": [{"item_id": widget["id"], "qty": "1"}],
        },
    )
    o.ok("POST", f"/api/v1/billing/credit-notes/{cn['id']}:issue")
    got = o.ok("GET", f"/api/v1/billing/invoices/{inv['id']}")
    assert D(got["credit_total"]) == D("1180.00") and D(got["amount_due"]) == D("1360.00")
    o.idem(
        "POST",
        "/api/v1/billing/payments",
        json={
            "account_id": cust["id"],
            "amount": "1360",
            "method": "bank_transfer",
            "allocations": [{"invoice_id": inv["id"], "amount": "1360"}],
        },
    )
    got = o.ok("GET", f"/api/v1/billing/invoices/{inv['id']}")
    assert got["payment_status"] == "paid" and D(got["amount_due"]) == 0 and len(got["payments"]) == 2
    # over-allocation refused
    r = o.post(
        "/api/v1/billing/payments",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "account_id": cust["id"],
            "amount": "10",
            "method": "cash",
            "allocations": [{"invoice_id": inv["id"], "amount": "10"}],
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "ALLOCATION_EXCEEDS_DUE"
    # cannot cancel an invoice with payments; refund then cancel
    r = o.post(f"/api/v1/billing/invoices/{inv['id']}:cancel", json={"reason": "wrong"})
    assert r.status_code == 409
    # reports reflect it
    dash = o.ok("GET", "/api/v1/reports/dashboard")
    assert D(dash["sales"]["this_month"]) >= D("3540.00")
    gst = o.ok("GET", "/api/v1/reports/gst-summary")
    assert any(b["number"] == issued["number"] for b in gst["b2b"]) and gst["notes"]
    csv = o.get("/api/v1/reports/gst-summary?format=csv&section=hsn")
    assert csv.status_code == 200 and "hsn" in csv.text.splitlines()[0]


def test_inter_state_invoice_and_gst_validation(app, company):
    o = company["owner"]
    b2c = o.ok("POST", "/api/v1/crm/accounts", json={"name": "Walk-in", "state_code": "27"})
    inv = o.idem(
        "POST",
        "/api/v1/billing/invoices",
        json={
            "account_id": company["inter_customer"]["id"],
            "lines": [{"item_id": company["service"]["id"], "qty": "2"}],
        },
    )
    assert D(inv["igst_total"]) == D("180.00") and D(inv["cgst_total"]) == 0 and inv["scenario"] == "b2b"
    # B2B without recipient GSTIN is rejected at issue
    bad = o.idem(
        "POST",
        "/api/v1/billing/invoices",
        json={
            "account_id": b2c["id"],
            "scenario": "b2b",
            "lines": [{"description": "Consulting", "qty": "1", "rate": "100"}],
        },
    )
    r = o.post(f"/api/v1/billing/invoices/{bad['id']}:issue", headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 422 and r.json()["error"]["code"] == "GST_SCENARIO_INVALID"
    # numbers are sequential and gapless
    n1 = o.idem("POST", f"/api/v1/billing/invoices/{inv['id']}:issue")["number"]
    inv2 = o.idem(
        "POST",
        "/api/v1/billing/invoices",
        json={"account_id": b2c["id"], "lines": [{"description": "X", "qty": "1", "rate": "50"}]},
    )
    n2 = o.idem("POST", f"/api/v1/billing/invoices/{inv2['id']}:issue")["number"]
    assert int(n2[-5:]) == int(n1[-5:]) + 1
    # issued invoice is immutable; cancel works (no payments)
    assert o.patch(f"/api/v1/billing/invoices/{inv['id']}", json={"lines": []}).status_code == 409
    c = o.ok("POST", f"/api/v1/billing/invoices/{inv['id']}:cancel", json={"reason": "duplicate"})
    assert c["document_status"] == "cancelled"


def test_idempotency_replay_and_conflict(app, company):
    o = company["owner"]
    body = {
        "account_id": company["customer"]["id"],
        "lines": [{"item_id": company["service"]["id"], "qty": "1"}],
    }
    key = str(uuid.uuid4())
    a = o.idem("POST", "/api/v1/sales/quotations", json=body, key=key)
    b = o.idem("POST", "/api/v1/sales/quotations", json=body, key=key)
    assert a["id"] == b["id"]
    r = o.post(
        "/api/v1/sales/quotations", json={**body, "notes": "different"}, headers={"Idempotency-Key": key}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    r = o.post("/api/v1/sales/quotations", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert len([x for x in o.ok("GET", "/api/v1/sales/quotations")["data"]]) == 1


def test_discount_approval_flow(app, company):
    o = company["owner"]
    exec_ = add_member(app, o, "sales_exec")
    q = exec_.idem(
        "POST",
        "/api/v1/sales/quotations",
        json={
            "account_id": company["customer"]["id"],
            "lines": [{"item_id": company["widget"]["id"], "qty": "1", "discount_pct": "25"}],
        },
    )
    assert q["approval_status"] == "pending"
    r = exec_.post(f"/api/v1/sales/quotations/{q['id']}:send")
    assert r.status_code == 409 and r.json()["error"]["code"] == "APPROVAL_REQUIRED"
    assert exec_.post(f"/api/v1/sales/quotations/{q['id']}:approve").status_code == 403
    notes = o.ok("GET", "/api/v1/notifications")
    assert any("approval" in n["title"].lower() for n in notes["data"])
    o.ok("POST", f"/api/v1/sales/quotations/{q['id']}:approve")
    assert exec_.ok("POST", f"/api/v1/sales/quotations/{q['id']}:send")["status"] == "sent"
    assert exec_.ok("GET", "/api/v1/notifications")["unread"] >= 1


def test_insufficient_stock_blocks_confirm(app, company):
    o = company["owner"]
    so = o.idem(
        "POST",
        "/api/v1/sales/orders",
        json={
            "account_id": company["customer"]["id"],
            "lines": [{"item_id": company["widget"]["id"], "qty": "50"}],
        },
    )
    r = o.post(f"/api/v1/sales/orders/{so['id']}:confirm")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert o.ok("GET", f"/api/v1/sales/orders/{so['id']}")["status"] == "draft"  # rolled back
    o.ok("POST", f"/api/v1/sales/orders/{so['id']}:cancel")


def test_procure_to_stock_and_transfers(app, company):
    o, widget = company["owner"], company["widget"]
    vendor = o.ok("POST", "/api/v1/procurement/vendors", json={"name": "Supplier Co", "state_code": "36"})
    po = o.idem(
        "POST",
        "/api/v1/procurement/purchase-orders",
        json={"vendor_id": vendor["id"], "lines": [{"item_id": widget["id"], "qty": "5"}]},
    )
    assert D(po["lines"][0]["rate"]) == D("600.00") and po["number"].startswith("PO/")
    r = o.post(
        f"/api/v1/procurement/purchase-orders/{po['id']}/receipts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"lines": [{"line_id": po["lines"][0]["id"], "qty": "1"}]},
    )
    assert r.status_code == 409  # not approved yet
    o.ok("POST", f"/api/v1/procurement/purchase-orders/{po['id']}:submit")
    o.ok("POST", f"/api/v1/procurement/purchase-orders/{po['id']}:approve")
    part = o.idem(
        "POST",
        f"/api/v1/procurement/purchase-orders/{po['id']}/receipts",
        json={"lines": [{"line_id": po["lines"][0]["id"], "qty": "2"}]},
    )
    assert part["status"] == "partially_received" and stock_of(o, widget["id"]) == D("12")
    r = o.post(
        f"/api/v1/procurement/purchase-orders/{po['id']}/receipts",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"lines": [{"line_id": po["lines"][0]["id"], "qty": "4"}]},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "OVER_RECEIPT"
    done = o.idem(
        "POST",
        f"/api/v1/procurement/purchase-orders/{po['id']}/receipts",
        json={"lines": [{"line_id": po["lines"][0]["id"], "qty": "3"}]},
    )
    assert done["status"] == "received" and stock_of(o, widget["id"]) == D("15")
    # transfer to a second warehouse
    w2 = o.ok("POST", "/api/v1/inventory/warehouses", json={"name": "Branch", "code": "BR1"})
    t = o.idem(
        "POST",
        "/api/v1/inventory/transfers",
        json={
            "from_warehouse_id": company["warehouse"]["id"],
            "to_warehouse_id": w2["id"],
            "lines": [{"item_id": widget["id"], "qty": "4"}],
        },
    )
    o.ok("POST", f"/api/v1/inventory/transfers/{t['id']}:dispatch")
    o.ok("POST", f"/api/v1/inventory/transfers/{t['id']}:receive")
    per_wh = {
        w["warehouse"]: D(w["on_hand"])
        for w in o.ok("GET", f"/api/v1/inventory/stock/{widget['id']}")["warehouses"]
    }
    assert per_wh == {"Main warehouse": D("11"), "Branch": D("4")}
    ledger = o.ok("GET", f"/api/v1/inventory/ledger?item_id={widget['id']}")["data"]
    assert {x["reason"] for x in ledger} >= {"opening", "receipt", "transfer_out", "transfer_in"}
    # negative adjustment beyond stock refused
    r = o.post(
        "/api/v1/inventory/adjustments",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"item_id": widget["id"], "warehouse_id": w2["id"], "qty_change": "-5", "reason": "damage"},
    )
    assert r.status_code == 409


def test_lead_conversion_and_tasks(app, company):
    o = company["owner"]
    exec_ = add_member(app, o, "sales_exec")
    exec_id = exec_.ok("GET", "/api/v1/me")["user"]["id"]
    lead = o.ok(
        "POST",
        "/api/v1/crm/leads",
        json={
            "name": "Ravi",
            "company": "Ravi Foods",
            "email": "ravi@foods.example",
            "owner_id": exec_id,
            "estimated_value": "75000",
        },
    )
    dup = o.ok("POST", "/api/v1/crm/leads", json={"name": "Ravi again", "email": "RAVI@foods.example"})
    assert dup["duplicates"] and dup["duplicates"][0]["id"] == lead["id"]
    assert any(n["title"].startswith("New lead") for n in exec_.ok("GET", "/api/v1/notifications")["data"])
    conv = exec_.ok("POST", f"/api/v1/crm/leads/{lead['id']}:convert", json={"create_opportunity": True})
    assert (
        conv["opportunity_id"] and exec_.ok("GET", f"/api/v1/crm/leads/{lead['id']}")["status"] == "converted"
    )
    opp = exec_.ok("GET", "/api/v1/crm/opportunities")["data"][0]
    assert D(opp["value"]) == D("75000.00")
    pipes = o.ok("GET", "/api/v1/crm/pipelines")[0]
    won = next(s for s in pipes["stages"] if s["outcome"] == "won")
    assert (
        exec_.ok("PATCH", f"/api/v1/crm/opportunities/{opp['id']}", json={"stage_id": won["id"]})["status"]
        == "won"
    )
    task = o.ok(
        "POST",
        "/api/v1/crm/activities",
        json={
            "type": "task",
            "subject": "Call back",
            "assigned_to": exec_id,
            "related_type": "account",
            "related_id": conv["account_id"],
        },
    )
    mine = exec_.ok("GET", "/api/v1/crm/activities?assigned=me&type=task&status=open")["data"]
    assert [t["id"] for t in mine] == [task["id"]]
    exec_.ok("PATCH", f"/api/v1/crm/activities/{task['id']}", json={"done": True})
    assert exec_.ok("GET", "/api/v1/crm/activities?assigned=me&type=task&status=open")["data"] == []
    dash = exec_.ok("GET", "/api/v1/reports/dashboard")
    assert "my_tasks" in dash and "receivables" not in dash  # role-aware sections


def test_outbox_relay_and_consumers(app, company):
    from manima.core.models import Notification, OutboxEvent
    from manima.shared.db import platform_session_factory, session_factory, set_tenant
    from manima.workers.events import relay_once

    o = company["owner"]
    item = company["widget"]
    o.ok("PATCH", f"/api/v1/catalog/items/{item['id']}", json={"reorder_level": "9"})
    o.idem(
        "POST",
        "/api/v1/inventory/adjustments",
        json={
            "item_id": item["id"],
            "warehouse_id": company["warehouse"]["id"],
            "qty_change": "-2",
            "reason": "damage",
        },
    )
    published = 0
    while (n := relay_once()) > 0:
        published += n
    assert published >= 1
    tid = o.ok("GET", "/api/v1/me")["active_tenant"]["id"]
    with session_factory()() as db:
        set_tenant(db, uuid.UUID(tid))
        assert db.scalar(select(Notification).where(Notification.title.like("Low stock%")))
    with platform_session_factory()() as db:
        assert (
            db.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.tenant_id == uuid.UUID(tid), OutboxEvent.published_at.is_(None)
                )
            )
            is None
        )
    # replaying the same event is a no-op (consumer dedupe)
    from manima.workers.events import process_event

    with platform_session_factory()() as db:
        ev = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "stock.changed", OutboxEvent.tenant_id == uuid.UUID(tid)
            )
        )
    process_event(ev.id)
    with session_factory()() as db:
        set_tenant(db, uuid.UUID(tid))
        assert len(db.scalars(select(Notification).where(Notification.title.like("Low stock%"))).all()) == 1


def test_failed_transaction_writes_no_outbox_row(app, company):
    from manima.core.models import OutboxEvent
    from manima.shared.db import platform_session_factory

    o = company["owner"]
    tid = uuid.UUID(o.ok("GET", "/api/v1/me")["active_tenant"]["id"])
    with platform_session_factory()() as db:
        before = db.query(OutboxEvent).filter(OutboxEvent.tenant_id == tid).count()
    so = o.idem(
        "POST",
        "/api/v1/sales/orders",
        json={
            "account_id": company["customer"]["id"],
            "lines": [{"item_id": company["widget"]["id"], "qty": "999"}],
        },
    )
    o.post(f"/api/v1/sales/orders/{so['id']}:confirm")  # fails: insufficient stock
    with platform_session_factory()() as db:
        after = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.tenant_id == tid, OutboxEvent.event_type == "order.confirmed")
            .count()
        )
    assert after == 0 and before >= 1


def test_platform_admin_flows(app):
    sa = super_admin(app)
    t = sa.ok(
        "POST",
        "/api/v1/platform/tenants",
        json={
            "legal_name": "Platform Made Co",
            "owner_email": f"pm{uuid.uuid4().hex[:6]}@example.com",
            "owner_name": "PM Owner",
            "plan_key": "starter",
        },
    )
    assert t["owner_temp_password"] and t["plan_key"] == "starter"
    detail = sa.ok("GET", f"/api/v1/platform/tenants/{t['id']}")
    assert {m["key"] for m in detail["modules"] if m["state"] == "enabled"} >= {"crm", "sales", "invoicing"}
    assert all(m["state"] == "disabled" for m in detail["modules"] if m["key"] == "inventory")
    dash = sa.ok("GET", "/api/v1/platform/dashboard")
    assert dash["tenants"]["total"] >= 1
    health = sa.ok("GET", "/api/v1/platform/health")
    assert health["checks"]["database"]["status"] == "ok"
    assert sa.ok("GET", "/api/v1/platform/audit?action=tenant.created")["total"] >= 1
    # tenant requests a plan change, platform approves
    owner, _ = signup(app)
    owner.ok("POST", "/api/v1/tenant/subscription:request-change", json={"plan_key": "enterprise"})
    pc = next(p for p in sa.ok("GET", "/api/v1/platform/plan-changes") if p["status"] == "requested")
    sa.ok("POST", f"/api/v1/platform/plan-changes/{pc['id']}:approve")
    assert owner.ok("GET", "/api/v1/tenant/subscription")["plan"]["key"] in ("enterprise", "growth")
    users = sa.ok("GET", "/api/v1/platform/users?staff_only=true")
    assert users["total"] >= 1
    # platform staff cannot read tenant business data
    assert sa.get("/api/v1/crm/leads").status_code == 400
