"""Celery worker + beat (ADR-0006). Run:

celery -A manima.workers.celery_app worker -Q critical,default -l info
celery -A manima.workers.celery_app beat -l info
python -m manima.workers.relay
"""

from __future__ import annotations

import time
from datetime import date

from celery import Celery
from sqlalchemy import update

import manima.models  # noqa: F401  (register all tables)
from manima.settings import get_settings
from manima.shared.db import platform_session_factory

settings = get_settings()
app = Celery("manima", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="default",
    task_routes={"manima.handle_event": {"queue": "critical"}},
    beat_schedule={
        "heartbeat": {"task": "manima.heartbeat", "schedule": 30.0},
        "expire-quotations": {"task": "manima.expire_quotations", "schedule": 3600.0},
    },
    timezone="Asia/Kolkata",
)


@app.task(name="manima.handle_event", bind=True, max_retries=5, default_retry_delay=10)
def handle_event(self, event_id: str) -> None:
    from manima.workers.events import process_event

    try:
        process_event(event_id)
    except Exception as exc:  # idempotent consumers: safe to retry
        raise self.retry(exc=exc, countdown=min(300, 10 * 2**self.request.retries)) from exc


@app.task(name="manima.heartbeat")
def heartbeat() -> None:
    import redis

    redis.Redis.from_url(settings.redis_url).set("manima:worker:heartbeat", str(time.time()), ex=600)


@app.task(name="manima.expire_quotations")
def expire_quotations() -> int:
    """Platform job: sent quotations past validity become expired (explicit, audited via outbox)."""
    from manima.modules.sales.module import Quotation

    with platform_session_factory()() as db:
        res = db.execute(
            update(Quotation)
            .where(Quotation.status == "sent", Quotation.valid_until < date.today())
            .values(status="expired")
        )
        db.commit()
        return res.rowcount or 0


def publish(event_id) -> None:
    handle_event.apply_async(args=[str(event_id)], queue="critical")
