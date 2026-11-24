# Manima One

Multi-tenant CRM + ERP for Indian SMBs (GST-native). A modular monolith: FastAPI + PostgreSQL with forced row-level security on the backend, Next.js on the frontend, and Celery workers fed by a transactional outbox.

```
apps/api/            FastAPI app, SQLAlchemy 2 models, Alembic migrations, Celery worker + outbox relay, tests
apps/web/            Next.js 16 (App Router), React 19, TypeScript, Tailwind v4, owned shadcn-style components
infrastructure/      Dockerfiles, Postgres role bootstrap, Terraform (AWS ap-south-1: VPC, ECS Fargate, RDS, Valkey, ALB)
tests/e2e/           Playwright browser tests (all pages × roles sweep; lead → invoice → payment workflow)
.github/workflows/   ci-api, ci-web, e2e, infra
```

## Run it

### Docker Compose

```bash
cp .env.example .env          # set real passwords
docker compose up --build     # postgres, valkey, migrate (+ super admin bootstrap), api, relay, worker, beat, web
docker compose run --rm migrate python -m manima.cli seed-demo   # optional demo company
```

Web: http://localhost:3000 · API docs: http://localhost:8000/api/docs

### Native (no Docker)

Requires Python ≥ 3.12 with `uv`, Node 24, PostgreSQL 16, Redis or Valkey.

```bash
# one-time, as a Postgres superuser: the three roles (see infrastructure/docker/postgres-init.sh)
psql -U postgres -c "create role manima login password 'manima' createdb"
psql -U postgres -c "create role manima_app login password 'manima_app' nobypassrls"
psql -U postgres -c "create role manima_platform login password 'manima_platform' bypassrls"
psql -U postgres -c "create database manima owner manima"
psql -U postgres -d manima -c "create extension citext"

make install migrate
MANIMA_BOOTSTRAP_ADMIN_EMAIL=admin@manima.local MANIMA_BOOTSTRAP_ADMIN_PASSWORD='Admin@12345' make bootstrap
make seed                        # demo tenant "Sunrise Traders", one user per role, password Demo@12345
make api   # :8000      (separate terminals)
make relay
make worker
make web   # :3000
```

Demo sign-ins after `make seed`: `owner@`, `admin@`, `salesmanager@`, `sales@`, `accounts@`, `store@`, `viewer@demo.manima.local` (password `Demo@12345`). The super admin is whatever you bootstrapped.

## Tests

```bash
make test    # 51 backend tests on real Postgres: unit (GST), integration (auth, RBAC, workflows,
             # entitlements, outbox), isolation (cross-tenant, release-blocking), contract (route audit)
make lint    # ruff + eslint + tsc
make e2e     # browser: 167 page loads across 6 roles + the order-to-cash workflow
```

The test DB is `manima_test` (owned by `manima`). Override with `MANIMA_TEST_OWNER_URL`, `MANIMA_TEST_APP_URL` and `MANIMA_TEST_PLATFORM_URL`.

## Security model

- **Three database roles.** `manima` owns the schema and is used only by migrations. `manima_app` is the API runtime role: NOBYPASSRLS, and every tenant table has **forced** RLS keyed on `app.tenant_id`, which is set per transaction from the server-side session. With no tenant set, queries return zero rows. `manima_platform` (BYPASSRLS) is used only by the outbox relay, workers, CLI and platform-admin metadata routes. There is no session setting that lets the runtime role read another tenant's rows; a test asserts this.
- **Composite tenant foreign keys** `(tenant_id, x_id)` block cross-tenant links at the database level.
- **Sessions:** an opaque HttpOnly cookie whose SHA-256 is stored server-side, so revocation is instant. Writes require `X-Requested-With: manima` (CSRF). In non-local environments the cookie is forced to `Secure` with the `__Host-` prefix. Login is rate-limited (Valkey-backed, 429 with `Retry-After`).
- **Authorization:** every route goes through `require(permission)`, which runs the entitlement engine (tenant status → kill switch → plan/override → module state → role → limits). A contract test fails the build if a route has no guard. Users with only `*.read_own` permissions see only their own records.
- **Audit:** an append-only `audit_events` table (UPDATE/DELETE revoked) for tenant and platform actions.

## Background work

Business transactions write domain events to `outbox_events` in the same transaction. `manima.workers.relay` publishes them to Celery (Valkey broker). Consumers are deduplicated through `processed_events`, retried with backoff, and dead-lettered after repeated failures (replayable from Admin → System health). Beat runs the heartbeat and quotation expiry.

## Deviations from the design docs

| Doc says | Built | Why |
|---|---|---|
| Amazon Cognito OIDC (ADR-0005) | Local email + password (scrypt) behind the same app-owned session model | No Cognito pool or credentials available; the swap stays inside `core/routes_auth.py` + `core/security.py` |
| Python 3.14 (ADR-0002), PostgreSQL 18 (ADR-0003) | `requires-python >=3.12`, PostgreSQL 16 | The build brief set the 3.12 / PG16 baseline; tested on Python 3.13 + PG 16.15 |
| pnpm workspace + generated API client (ADR-0009) | npm in `apps/web`, hand-written typed fetch client | Fewer moving parts; OpenAPI is at `/api/openapi.json` for client generation later |
| Cursor pagination | `limit`/`offset` with `total` | Numbered pages in the UI |
| WeasyPrint PDFs (ADR-0015) | Print-optimised invoice view → browser "Save as PDF" | No server-side PDF rendering yet |
