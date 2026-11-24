"""Audit trail, transactional outbox writer and in-app notifications."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from manima.core.models import AuditEvent, Notification, OutboxEvent

if TYPE_CHECKING:
    from manima.core.security import Ctx

REDACT = {"password", "password_hash", "token", "token_hash", "secret"}


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: ("***" if k in REDACT else _jsonable(x)) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, uuid.UUID | Decimal):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


def snapshot(obj, fields: tuple[str, ...] | None = None) -> dict:
    cols = fields or tuple(c.key for c in obj.__table__.columns)
    return _jsonable({c: getattr(obj, c) for c in cols})


def audit(
    db: Session,
    ctx: Ctx | None,
    action: str,
    resource_type: str,
    resource_id: Any = None,
    *,
    before: dict | None = None,
    after: dict | None = None,
    tenant_id: uuid.UUID | None = None,
    platform: bool = False,
) -> None:
    tid = None if platform else (tenant_id or (ctx.tenant_id if ctx else None))
    db.add(
        AuditEvent(
            tenant_id=tid,
            actor_id=ctx.user.id if ctx else None,
            actor_type="user" if ctx else "system",
            actor_email=ctx.user.email if ctx else None,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            before=_jsonable(before) if before else None,
            after=_jsonable(after) if after else None,
            request_id=ctx.request_id if ctx else None,
        )
    )


def emit(
    db: Session,
    tenant_id: uuid.UUID | None,
    event_type: str,
    aggregate_type: str,
    aggregate_id: Any,
    payload: dict | None = None,
    version: int = 1,
) -> None:
    """Write a domain event in the caller's transaction (ADR-0006)."""
    db.add(
        OutboxEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            event_version=version,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            payload=_jsonable(payload or {}),
        )
    )


def notify(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    body: str | None = None,
    link: str | None = None,
    kind: str = "info",
) -> None:
    db.add(Notification(tenant_id=tenant_id, user_id=user_id, title=title, body=body, link=link, kind=kind))
