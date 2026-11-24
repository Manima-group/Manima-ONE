"""Remove the session-settable RLS bypass; cross-tenant work uses the BYPASSRLS platform role.

The runtime role (manima_app) can no longer see another tenant's rows by any means.
The platform role (manima_platform, created by the DB bootstrap script because only a
superuser may grant BYPASSRLS) is used by the outbox relay, workers, CLI and platform metadata.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Frozen copy of the 0002 table list: migrations must not import each other.
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
PLATFORM_ROLE = "manima_platform"
TENANT_PRED = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    for t in TENANT_TABLES:
        op.execute(f"drop policy if exists tenant_isolation on app.{t}")
        op.execute(
            f"create policy tenant_isolation on app.{t} using ({TENANT_PRED}) with check ({TENANT_PRED})"
        )
    for t in ("audit_events", "outbox_events"):
        for p in ("tenant_read", "tenant_write", "relay_update"):
            op.execute(f"drop policy if exists {p} on app.{t}")
        op.execute(f"create policy tenant_read on app.{t} for select using ({TENANT_PRED})")
        # Platform actions record tenant_id NULL audit rows; the runtime role can write but never read them.
        op.execute(
            f"create policy tenant_write on app.{t} for insert with check ({TENANT_PRED} or tenant_id is null)"
        )
    op.execute(f"""
    do $$ begin
      if exists (select 1 from pg_roles where rolname = '{PLATFORM_ROLE}') then
        grant usage on schema app to {PLATFORM_ROLE};
        grant select, insert, update, delete on all tables in schema app to {PLATFORM_ROLE};
        alter default privileges in schema app grant select, insert, update, delete on tables
          to {PLATFORM_ROLE};
        revoke update, delete on app.audit_events from {PLATFORM_ROLE};
      else
        raise warning 'role {PLATFORM_ROLE} missing: run infrastructure/docker/postgres-init.sql';
      end if;
    end $$;
    """)


def downgrade() -> None:
    bypass = "current_setting('app.bypass_rls', true) = 'on'"
    for t in TENANT_TABLES:
        op.execute(f"drop policy if exists tenant_isolation on app.{t}")
        op.execute(
            f"create policy tenant_isolation on app.{t} using ({TENANT_PRED} or {bypass}) "
            f"with check ({TENANT_PRED} or {bypass})"
        )
