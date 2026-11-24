"""Test harness: real PostgreSQL (manima_test), fresh migrations, runtime role under forced RLS."""

from __future__ import annotations

import os
import uuid

import pytest

OWNER_URL = os.environ.get(
    "MANIMA_TEST_OWNER_URL", "postgresql+psycopg://manima:manima@localhost:5432/manima_test"
)
APP_URL = os.environ.get(
    "MANIMA_TEST_APP_URL", "postgresql+psycopg://manima_app:manima_app@localhost:5432/manima_test"
)
PLATFORM_URL = os.environ.get(
    "MANIMA_TEST_PLATFORM_URL",
    "postgresql+psycopg://manima_platform:manima_platform@localhost:5432/manima_test",
)
os.environ["MANIMA_DATABASE_URL"] = APP_URL
os.environ["MANIMA_PLATFORM_DATABASE_URL"] = PLATFORM_URL
os.environ["MANIMA_MIGRATION_DATABASE_URL"] = OWNER_URL
os.environ["MANIMA_ENVIRONMENT"] = "test"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402

from manima.settings import get_settings  # noqa: E402

get_settings.cache_clear()

PASSWORD = "Test@123456"


def _alembic_cfg() -> Config:
    here = os.path.dirname(os.path.dirname(__file__))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "src/manima/migrations"))
    cfg.set_main_option("sqlalchemy.url", OWNER_URL)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def database():
    eng = create_engine(OWNER_URL, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text("drop schema if exists app cascade"))
        c.execute(text("drop table if exists public.alembic_version"))
    eng.dispose()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "head")
    from manima.cli import _session
    from manima.core.provisioning import sync_registry
    from manima.shared.db import reset_engine

    reset_engine()
    with _session() as db:
        sync_registry(db)
        db.commit()
    yield cfg


@pytest.fixture(scope="session")
def app(database):
    from manima.main import create_app

    return create_app()


class Api:
    """TestClient wrapper that always sends the CSRF header and unwraps JSON."""

    def __init__(self, app):
        self.c = TestClient(app)
        self.c.headers.update({"X-Requested-With": "manima"})

    def __getattr__(self, name):
        return getattr(self.c, name)

    def ok(self, method: str, url: str, status: int | tuple = (200, 201), **kw):
        r = self.c.request(method, url, **kw)
        expected = status if isinstance(status, tuple) else (status,)
        assert r.status_code in expected, f"{method} {url} -> {r.status_code}: {r.text}"
        return r.json()

    def idem(self, method: str, url: str, json=None, key: str | None = None, **kw):
        return self.ok(method, url, json=json, headers={"Idempotency-Key": key or str(uuid.uuid4())}, **kw)


@pytest.fixture
def api(app):
    return Api(app)


@pytest.fixture
def new_api(app):
    return lambda: Api(app)


def signup(app, company: str | None = None, state_code: str = "36") -> tuple[Api, dict]:
    a = Api(app)
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    me = a.ok(
        "POST",
        "/api/v1/signup",
        json={
            "company_name": company or f"Co {uuid.uuid4().hex[:6]}",
            "name": "Owner One",
            "email": email,
            "password": PASSWORD,
            "state_code": state_code,
        },
    )
    me["email"] = email
    return a, me


def add_member(app, owner: Api, role_key: str) -> Api:
    roles = owner.ok("GET", "/api/v1/tenant/roles")
    rid = next(r["id"] for r in roles if r["key"] == role_key)
    email = f"{role_key}-{uuid.uuid4().hex[:8]}@example.com"
    inv = owner.ok(
        "POST", "/api/v1/tenant/invitations", json={"email": email, "name": role_key, "role_ids": [rid]}
    )
    token = inv["accept_path"].rsplit("/", 1)[-1]
    m = Api(app)
    m.ok(
        "POST",
        "/api/v1/invitations/accept",
        json={"token": token, "name": f"{role_key} user", "password": PASSWORD},
    )
    return m


def super_admin(app) -> Api:
    from manima.cli import _session, ensure_user
    from manima.core.models import PlatformRoleAssignment, Role

    email = f"sa-{uuid.uuid4().hex[:6]}@manima.local"
    with _session() as db:
        u = ensure_user(db, email, "SA", PASSWORD)
        rid = db.scalar(select(Role.id).where(Role.tenant_id.is_(None), Role.key == "super_admin"))
        db.add(PlatformRoleAssignment(user_id=u.id, role_id=rid))
        db.commit()
    a = Api(app)
    a.ok("POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return a


def gstin(state: str = "36", pan: str = "AABCT1234E") -> str:
    from manima.modules.compliance_gst.domain import gstin_checksum_char

    base = f"{state}{pan}1Z"
    return base + gstin_checksum_char(base)


@pytest.fixture
def company(app):
    """Owner of a fresh company with a GST registration, a customer and two items with stock."""
    owner, me = signup(app)
    owner.ok(
        "POST",
        "/api/v1/tenant/gst-registrations",
        json={"gstin": gstin("36", "AAACS1234F"), "legal_name": "Seller Pvt Ltd"},
    )
    cust = owner.ok(
        "POST", "/api/v1/crm/accounts", json={"name": "Buyer Ltd", "gstin": gstin("36", "AAACB1234G")}
    )
    inter = owner.ok(
        "POST", "/api/v1/crm/accounts", json={"name": "Mumbai Buyer", "gstin": gstin("27", "AAACM1234H")}
    )
    widget = owner.ok(
        "POST",
        "/api/v1/catalog/items",
        json={
            "sku": "W-1",
            "name": "Widget",
            "price": "1000",
            "purchase_price": "600",
            "gst_rate": "18",
            "hsn_sac": "8471",
            "reorder_level": "2",
        },
    )
    svc = owner.ok(
        "POST",
        "/api/v1/catalog/items",
        json={
            "sku": "S-1",
            "name": "Support",
            "type": "service",
            "price": "500",
            "gst_rate": "18",
            "hsn_sac": "998313",
        },
    )
    wh = owner.ok("GET", "/api/v1/inventory/warehouses")[0]
    owner.idem(
        "POST",
        "/api/v1/inventory/adjustments",
        json={"item_id": widget["id"], "warehouse_id": wh["id"], "qty_change": "10", "reason": "opening"},
    )
    return {
        "owner": owner,
        "me": me,
        "customer": cust,
        "inter_customer": inter,
        "widget": widget,
        "service": svc,
        "warehouse": wh,
    }
