"""Operational commands.

python -m manima.cli sync                 # upsert module registry, permissions, platform roles, default plans
python -m manima.cli bootstrap            # sync + create super admin from MANIMA_BOOTSTRAP_ADMIN_* env vars
python -m manima.cli seed-demo            # local/dev only: demo company, one employee per role, sample data
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

import manima.models  # noqa: F401
from manima.core.models import MemberRole, PlatformRoleAssignment, PlatformUser, Role, TenantMembership
from manima.core.provisioning import provision_tenant, sync_registry
from manima.core.security import hash_password
from manima.settings import get_settings
from manima.shared.db import platform_session_factory, set_tenant


def _session():
    return platform_session_factory()()


def cmd_sync() -> None:
    with _session() as db:
        sync_registry(db)
        db.commit()
    print("registry synced")


def ensure_user(db, email: str, name: str, password: str) -> PlatformUser:
    u = db.scalar(select(PlatformUser).where(PlatformUser.email == email))
    if u is None:
        u = PlatformUser(email=email, name=name, password_hash=hash_password(password))
        db.add(u)
        db.flush()
    return u


def cmd_bootstrap() -> None:
    s = get_settings()
    if not s.bootstrap_admin_email or not s.bootstrap_admin_password:
        sys.exit("Set MANIMA_BOOTSTRAP_ADMIN_EMAIL and MANIMA_BOOTSTRAP_ADMIN_PASSWORD")
    with _session() as db:
        sync_registry(db)
        u = ensure_user(db, s.bootstrap_admin_email.lower(), "Manima Super Admin", s.bootstrap_admin_password)
        rid = db.scalar(select(Role.id).where(Role.tenant_id.is_(None), Role.key == "super_admin"))
        if not db.get(PlatformRoleAssignment, (u.id, rid)):
            db.add(PlatformRoleAssignment(user_id=u.id, role_id=rid))
        u.mfa_required = True
        db.commit()
    print(f"super admin ready: {s.bootstrap_admin_email}")


DEMO_PASSWORD = "Demo@12345"  # local seed only; refuses to run in production
DEMO_USERS = [
    ("owner", "Asha Rao", "owner@demo.manima.local"),
    ("admin", "Vikram Shah", "admin@demo.manima.local"),
    ("sales_manager", "Priya Nair", "salesmanager@demo.manima.local"),
    ("sales_exec", "Rahul Verma", "sales@demo.manima.local"),
    ("accounts", "Meera Iyer", "accounts@demo.manima.local"),
    ("store_keeper", "Suresh Kumar", "store@demo.manima.local"),
    ("viewer", "Kiran Das", "viewer@demo.manima.local"),
]


def cmd_seed_demo() -> None:
    if get_settings().environment == "production":
        sys.exit("seed-demo is disabled in production")
    from manima.modules.catalog.module import Item
    from manima.modules.compliance_gst.models import GstRegistration
    from manima.modules.crm.module import Account, Contact, Lead
    from manima.modules.inventory.module import default_warehouse, move_stock
    from manima.modules.procurement.module import Vendor

    with _session() as db:
        sync_registry(db)
        if db.scalar(select(PlatformUser.id).where(PlatformUser.email == DEMO_USERS[0][2])):
            print("demo already seeded")
            return
        owner = ensure_user(db, DEMO_USERS[0][2], DEMO_USERS[0][1], DEMO_PASSWORD)
        t = provision_tenant(
            db,
            legal_name="Sunrise Traders Pvt Ltd",
            owner=owner,
            plan_key="growth",
            trial_days=None,
            state_code="36",
            slug="sunrise-traders",
        )
        tid = t.id
        set_tenant(db, tid)
        roles = {r.key: r for r in db.scalars(select(Role).where(Role.tenant_id == tid))}
        users = {"owner": owner}
        for key, name, email in DEMO_USERS[1:]:
            u = ensure_user(db, email, name, DEMO_PASSWORD)
            m = TenantMembership(tenant_id=tid, user_id=u.id, status="active", title=roles[key].name)
            db.add(m)
            db.flush()
            db.add(MemberRole(membership_id=m.id, role_id=roles[key].id))
            users[key] = u
        db.add(
            GstRegistration(
                tenant_id=tid,
                gstin="36AABCS1429B1Z5",
                legal_name="Sunrise Traders Pvt Ltd",
                trade_name="Sunrise Traders",
                state_code="36",
                is_default=True,
                address={
                    "line1": "Plot 12, HITEC City",
                    "city": "Hyderabad",
                    "state_code": "36",
                    "pincode": "500081",
                },
            )
        )
        items = [
            ("LAP-14", 'Business Laptop 14"', "goods", "8471", "nos", 18, 58000, 49000, 5),
            ("MON-24", '24" LED Monitor', "goods", "8528", "nos", 18, 11500, 9200, 10),
            ("UPS-1K", "UPS 1 kVA", "goods", "8504", "nos", 18, 6200, 4800, 8),
            ("CAB-C6", "Cat6 Cable (305m box)", "goods", "8544", "box", 18, 9800, 7600, 4),
            ("CHR-ERG", "Ergonomic Office Chair", "goods", "9401", "nos", 18, 8900, 6500, 6),
            ("SVC-AMC", "Annual Maintenance Contract", "service", "998719", "nos", 18, 15000, 0, 0),
            ("SVC-INST", "Installation & Setup", "service", "998313", "hrs", 18, 1200, 0, 0),
        ]
        wh = default_warehouse(db, tid)
        for sku, name, typ, hsn, unit, gst, price, cost, reorder in items:
            it = Item(
                tenant_id=tid,
                sku=sku,
                name=name,
                type=typ,
                hsn_sac=hsn,
                unit=unit,
                gst_rate=Decimal(gst),
                price=Decimal(price),
                purchase_price=Decimal(cost),
                track_stock=typ == "goods",
                reorder_level=Decimal(reorder),
                category="IT Hardware" if typ == "goods" else "Services",
                is_sample=True,
            )
            db.add(it)
            db.flush()
            if typ == "goods" and wh:
                move_stock(
                    db,
                    tid,
                    it.id,
                    wh.id,
                    Decimal(reorder * 4),
                    "opening",
                    note="Opening stock",
                    unit_cost=Decimal(cost),
                )
        accs = [
            ("Apex Infotech LLP", "36AAKFA1234C1Z9", "36", "Hyderabad"),
            ("Bluewave Retail Pvt Ltd", "27AACCB5678D1ZJ", "27", "Mumbai"),
            ("Greenfield Schools", None, "36", "Secunderabad"),
        ]
        from manima.modules.compliance_gst.domain import gstin_checksum_char

        for name, gstin, st, city in accs:
            if gstin:
                gstin = gstin[:14] + gstin_checksum_char(gstin[:14])
            a = Account(
                tenant_id=tid,
                name=name,
                gstin=gstin,
                pan=gstin[2:12] if gstin else None,
                state_code=st,
                billing_address={"city": city, "state_code": st},
                owner_id=users["sales_exec"].id,
                is_sample=True,
                email=f"accounts@{name.split()[0].lower()}.example",
            )
            db.add(a)
            db.flush()
            db.add(
                Contact(
                    tenant_id=tid,
                    account_id=a.id,
                    name=f"Purchase Head, {name.split()[0]}",
                    is_primary=True,
                    email=f"purchase@{name.split()[0].lower()}.example",
                    phone="+919800000000",
                )
            )
        for i, (n, comp, st) in enumerate(
            [
                ("Anil Kapoor", "Nova Logistics", "new"),
                ("Sneha Reddy", "Pixel Studios", "contacted"),
                ("Farhan Ali", "Metro Pharma", "qualified"),
                ("Divya Menon", "Orbit Foods", "new"),
            ]
        ):
            db.add(
                Lead(
                    tenant_id=tid,
                    name=n,
                    company=comp,
                    status=st,
                    source="website",
                    is_sample=True,
                    email=f"{n.split()[0].lower()}@{comp.split()[0].lower()}.example",
                    phone=f"+9198100000{i:02d}",
                    owner_id=users["sales_exec"].id if i % 2 == 0 else users["sales_manager"].id,
                    estimated_value=Decimal(50000 * (i + 1)),
                )
            )
        vgst = "36AAFCV4321K1Z"
        db.add(
            Vendor(
                tenant_id=tid,
                name="Vertex Distributors",
                gstin=vgst + gstin_checksum_char(vgst),
                state_code="36",
                email="sales@vertex.example",
                phone="+914000000000",
                contact_person="Ravi",
            )
        )
        db.commit()
    print("demo seeded: tenant 'sunrise-traders'; users:")
    for key, _name, email in DEMO_USERS:
        print(f"  {key:14s} {email}  password={DEMO_PASSWORD}")
    _ = (date, timedelta)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    {"sync": cmd_sync, "bootstrap": cmd_bootstrap, "seed-demo": cmd_seed_demo}[cmd]()
