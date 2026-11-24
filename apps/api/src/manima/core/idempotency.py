"""Idempotency-Key handling (API_STANDARDS §6)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from manima.core.models import IdempotencyKey
from manima.core.security import Ctx
from manima.settings import get_settings
from manima.shared.http import AppError


def run_idempotent(ctx: Ctx, key: str | None, operation: str, body: Any, fn: Callable[[], Any]) -> Any:
    """Execute ``fn`` once per (tenant, operation, key); replay returns the stored response.

    ``fn`` must perform its writes and *not* commit; this helper commits the business
    writes together with the idempotency record in one transaction.
    """
    if not key:
        raise AppError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required.")
    if len(key) > 80:
        raise AppError(400, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key too long.")
    db = ctx.db
    req_hash = hashlib.sha256(
        json.dumps(jsonable_encoder(body), sort_keys=True, default=str).encode()
    ).hexdigest()
    existing = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == ctx.tenant_id,
            IdempotencyKey.operation == operation,
            IdempotencyKey.key == key,
            IdempotencyKey.expires_at > datetime.now(UTC),
        )
    )
    if existing:
        if existing.request_hash != req_hash:
            raise AppError(
                409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was used with a different request."
            )
        return existing.response_body
    result = jsonable_encoder(fn())
    stale = db.get(IdempotencyKey, (ctx.tenant_id, operation, key))
    if stale:
        db.delete(stale)
        db.flush()
    db.add(
        IdempotencyKey(
            tenant_id=ctx.tenant_id,
            operation=operation,
            key=key,
            request_hash=req_hash,
            response_status=200,
            response_body=result,
            expires_at=datetime.now(UTC) + timedelta(hours=get_settings().idempotency_ttl_hours),
        )
    )
    db.commit()
    return result
