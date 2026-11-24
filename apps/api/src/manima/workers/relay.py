"""Outbox relay process: polls the outbox and publishes to Celery (or runs inline with --inline)."""

from __future__ import annotations

import logging
import sys
import time

import manima.models  # noqa: F401
from manima.workers.events import process_event, relay_once


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    inline = "--inline" in sys.argv
    if inline:
        publish = process_event
    else:
        from manima.workers.celery_app import publish
    log = logging.getLogger("manima.relay")
    log.info("outbox relay started (inline=%s)", inline)
    while True:
        try:
            n = relay_once(publish)
            if inline:
                import redis

                from manima.settings import get_settings

                try:
                    redis.Redis.from_url(get_settings().redis_url).set(
                        "manima:worker:heartbeat", str(time.time()), ex=600
                    )
                except Exception as exc:  # heartbeat is best-effort; health page shows worker down
                    log.debug("heartbeat write failed: %s", exc)
        except Exception:
            log.exception("relay iteration failed")
            n = 0
        time.sleep(0.2 if n else 1.0)


if __name__ == "__main__":
    main()
