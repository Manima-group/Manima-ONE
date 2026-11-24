# Local development without Docker (PostgreSQL 16 + Redis/Valkey running locally).
API = apps/api
WEB = apps/web

.PHONY: install migrate bootstrap seed api relay worker web test lint e2e

install:
	cd $(API) && uv sync
	cd $(WEB) && npm ci

migrate:
	cd $(API) && uv run alembic upgrade head

bootstrap:   ## needs MANIMA_BOOTSTRAP_ADMIN_EMAIL / _PASSWORD
	cd $(API) && uv run python -m manima.cli bootstrap

seed:        ## demo company + one user per role (local only)
	cd $(API) && uv run python -m manima.cli seed-demo

api:
	cd $(API) && uv run uvicorn manima.main:app --reload --port 8000

relay:
	cd $(API) && uv run python -m manima.workers.relay

worker:
	cd $(API) && uv run celery -A manima.workers.celery_app worker -B -Q critical,default -l info

web:
	cd $(WEB) && npm run dev

test:
	cd $(API) && uv run pytest -o addopts="" -p no:warnings

lint:
	cd $(API) && uv run ruff check src tests && uv run ruff format --check src tests
	cd $(WEB) && npm run lint && npm run typecheck

e2e:         ## needs api, relay, worker and web running + seeded demo
	python tests/e2e/smoke.py && python tests/e2e/workflow.py
