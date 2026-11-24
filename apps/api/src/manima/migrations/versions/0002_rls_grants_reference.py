"""Forced row-level security, runtime-role grants, append-only tables, HSN/SAC reference data.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Every tenant-owned table (TENANT_ISOLATION.md layer 4). Keep in sync: tests/isolation asserts coverage.
TENANT_TABLES = [
    "accounts",
    "activities",
    "adjustment_note_lines",
    "adjustment_notes",
    "contacts",
    "gst_registrations",
    "idempotency_keys",
    "invoice_lines",
    "invoices",
    "items",
    "leads",
    "notifications",
    "number_series",
    "opportunities",
    "payment_allocations",
    "payments",
    "pipeline_stages",
    "pipelines",
    "purchase_order_lines",
    "purchase_orders",
    "quotation_lines",
    "quotations",
    "reservations",
    "sales_order_lines",
    "sales_orders",
    "stock_adjustments",
    "stock_balances",
    "stock_ledger",
    "stock_transfers",
    "tenant_settings",
    "vendors",
    "warehouses",
]
APPEND_ONLY = ["audit_events", "stock_ledger"]
RUNTIME_ROLE = "manima_app"

TENANT_PRED = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
BYPASS_PRED = "current_setting('app.bypass_rls', true) = 'on'"

HSN = [
    ("8471", "Computers and peripheral units", "hsn", 18),
    ("8517", "Telephones, smartphones, network equipment", "hsn", 18),
    ("8528", "Monitors and projectors", "hsn", 18),
    ("8443", "Printers and copiers", "hsn", 18),
    ("8504", "Transformers, UPS, power supplies", "hsn", 18),
    ("8544", "Insulated wire and cables", "hsn", 18),
    ("8536", "Switches, plugs, sockets (< 1000V)", "hsn", 18),
    ("8414", "Air pumps, fans, compressors", "hsn", 18),
    ("8415", "Air conditioning machines", "hsn", 28),
    ("8418", "Refrigerators and freezers", "hsn", 18),
    ("8450", "Washing machines", "hsn", 18),
    ("9403", "Other furniture", "hsn", 18),
    ("9401", "Seats and chairs", "hsn", 18),
    ("4819", "Cartons, boxes of paper", "hsn", 12),
    ("4820", "Registers, notebooks, stationery", "hsn", 12),
    ("3923", "Plastic articles for packing", "hsn", 18),
    ("7308", "Structures of iron or steel", "hsn", 18),
    ("7318", "Screws, bolts, nuts of iron or steel", "hsn", 18),
    ("3004", "Medicaments, packaged doses", "hsn", 12),
    ("3304", "Beauty and skin-care preparations", "hsn", 18),
    ("3401", "Soap", "hsn", 18),
    ("0401", "Milk and cream, not concentrated", "hsn", 0),
    ("1006", "Rice", "hsn", 5),
    ("0902", "Tea", "hsn", 5),
    ("0901", "Coffee", "hsn", 5),
    ("1701", "Cane or beet sugar", "hsn", 5),
    ("2201", "Mineral and aerated water", "hsn", 18),
    ("6109", "T-shirts, singlets, knitted", "hsn", 5),
    ("6203", "Men's suits, trousers", "hsn", 12),
    ("6403", "Footwear with leather uppers", "hsn", 18),
    ("8703", "Motor cars", "hsn", 28),
    ("4011", "New rubber tyres", "hsn", 28),
    ("2523", "Portland cement", "hsn", 28),
    ("7214", "Bars and rods of iron/steel", "hsn", 18),
    ("998311", "Management consulting services", "sac", 18),
    ("998313", "IT consulting and support services", "sac", 18),
    ("998314", "IT design and development services", "sac", 18),
    ("998315", "Hosting and IT infrastructure services", "sac", 18),
    ("998316", "IT infrastructure and network management", "sac", 18),
    ("997331", "Licensing of software", "sac", 18),
    ("998361", "Advertising services", "sac", 18),
    ("998371", "Market research services", "sac", 18),
    ("998521", "Employment and placement services", "sac", 18),
    ("998719", "Maintenance and repair services", "sac", 18),
    ("996511", "Road transport of goods", "sac", 5),
    ("996601", "Rental of cars with operator", "sac", 5),
    ("997212", "Rental of commercial property", "sac", 18),
    ("999293", "Commercial training and coaching", "sac", 18),
    ("998222", "Accounting and bookkeeping services", "sac", 18),
    ("998212", "Legal advisory services", "sac", 18),
    ("996331", "Restaurant and catering services", "sac", 5),
    ("998596", "Event management services", "sac", 18),
]


def upgrade() -> None:
    op.execute(f"""
    do $$ begin
      if not exists (select 1 from pg_roles where rolname = '{RUNTIME_ROLE}') then
        create role {RUNTIME_ROLE} login nosuperuser nobypassrls;
      end if;
    end $$;
    """)
    op.execute(f"grant usage on schema app to {RUNTIME_ROLE}")
    op.execute(f"grant select, insert, update, delete on all tables in schema app to {RUNTIME_ROLE}")
    op.execute(
        f"alter default privileges in schema app grant select, insert, update, delete on tables to {RUNTIME_ROLE}"
    )
    for t in APPEND_ONLY:
        op.execute(f"revoke update, delete on app.{t} from {RUNTIME_ROLE}")
    op.execute(f"revoke insert, update, delete on app.hsn_sac_codes from {RUNTIME_ROLE}")

    for t in TENANT_TABLES:
        op.execute(f"alter table app.{t} enable row level security")
        op.execute(f"alter table app.{t} force row level security")
        op.execute(
            f"create policy tenant_isolation on app.{t} using ({TENANT_PRED} or {BYPASS_PRED}) "
            f"with check ({TENANT_PRED} or {BYPASS_PRED})"
        )

    # Audit + outbox: tenant rows isolated; platform rows (tenant_id NULL) may be written by platform actions,
    # but are only readable under an explicit bypass (platform audit / relay).
    for t in ("audit_events", "outbox_events"):
        op.execute(f"alter table app.{t} enable row level security")
        op.execute(f"alter table app.{t} force row level security")
        op.execute(f"create policy tenant_read on app.{t} for select using ({TENANT_PRED} or {BYPASS_PRED})")
        op.execute(
            f"create policy tenant_write on app.{t} for insert with check "
            f"({TENANT_PRED} or tenant_id is null or {BYPASS_PRED})"
        )
        op.execute(
            f"create policy relay_update on app.{t} for update using ({BYPASS_PRED}) with check ({BYPASS_PRED})"
        )

    op.execute(
        "create index if not exists ix_outbox_unpublished on app.outbox_events (occurred_at) "
        "where published_at is null and dead = false"
    )

    values = ",".join(f"('{c}', '{d.replace(chr(39), chr(39) * 2)}', '{k}', {r})" for c, d, k, r in HSN)
    op.execute(
        f"insert into app.hsn_sac_codes (code, description, kind, default_rate) values {values} "
        "on conflict (code) do nothing"
    )


def downgrade() -> None:
    for t in TENANT_TABLES:
        op.execute(f"drop policy if exists tenant_isolation on app.{t}")
        op.execute(f"alter table app.{t} disable row level security")
    for t in ("audit_events", "outbox_events"):
        for p in ("tenant_read", "tenant_write", "relay_update"):
            op.execute(f"drop policy if exists {p} on app.{t}")
        op.execute(f"alter table app.{t} disable row level security")
    op.execute("drop index if exists app.ix_outbox_unpublished")
    op.execute("delete from app.hsn_sac_codes")
