"""Outbox relay + idempotent event consumers (ADR-0006).

relay_once(): claims unpublished outbox rows with FOR UPDATE SKIP LOCKED, hands each
to ``publish`` (Celery send or inline) and marks it published. If the broker drops a
message the consumer side is still safe: process_event() de-duplicates by
(consumer, event_id) in ``processed_events``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from manima.core.models import (
    MemberRole,
    Notification,
    OutboxEvent,
    ProcessedEvent,
    RolePermission,
    TenantMembership,
)
from manima.shared.db import platform_session_factory, session_factory, set_tenant

log = logging.getLogger("manima.events")
MAX_ATTEMPTS = 5

Handler = Callable[[Session, OutboxEvent], None]
CONSUMERS: dict[str, list[tuple[str, Handler]]] = {}


def consumer(event_type: str, name: str):
    def deco(fn: Handler) -> Handler:
        CONSUMERS.setdefault(event_type, []).append((name, fn))
        return fn

    return deco


# ---------------------------------------------------------------- consumers
@consumer("invitation.created", "notifications.invitation_email")
def send_invitation_email(db: Session, e: OutboxEvent) -> None:
    # No email provider configured in this environment: the adapter logs the message.
    log.info(
        "EMAIL to=%s subject='You are invited to %s' link=%s",
        e.payload.get("email"),
        e.payload.get("company"),
        e.payload.get("accept_path"),
    )


@consumer("message.requested", "messaging.email_adapter")
def send_document_email(db: Session, e: OutboxEvent) -> None:
    log.info(
        "EMAIL to=%s template=%s number=%s",
        e.payload.get("to"),
        e.payload.get("template"),
        e.payload.get("number"),
    )


@consumer("member.joined", "notifications.member_joined")
def member_joined(db: Session, e: OutboxEvent) -> None:
    inviter = e.payload.get("invited_by")
    if inviter and inviter != "None":
        db.add(
            Notification(
                tenant_id=e.tenant_id,
                user_id=uuid.UUID(inviter),
                kind="team",
                title="A new employee accepted your invitation",
                link="/settings/employees",
            )
        )


@consumer("stock.changed", "inventory.low_stock_alert")
def low_stock_alert(db: Session, e: OutboxEvent) -> None:
    from decimal import Decimal

    from manima.modules.catalog.module import Item

    if Decimal(e.payload.get("qty_change", "0")) >= 0:
        return
    item = db.get(Item, uuid.UUID(e.aggregate_id))
    on_hand = Decimal(e.payload.get("on_hand", "0"))
    if item is None or item.reorder_level <= 0 or on_hand > item.reorder_level:
        return
    link = f"/inventory/stock?item={item.id}"
    users = db.scalars(
        select(TenantMembership.user_id)
        .distinct()
        .join(MemberRole, MemberRole.membership_id == TenantMembership.id)
        .join(RolePermission, RolePermission.role_id == MemberRole.role_id)
        .where(
            TenantMembership.tenant_id == e.tenant_id,
            TenantMembership.status == "active",
            RolePermission.permission_key == "inventory.adjustment.create",
        )
    ).all()
    for u in users:
        exists = db.scalar(
            select(Notification.id).where(
                Notification.tenant_id == e.tenant_id,
                Notification.user_id == u,
                Notification.link == link,
                Notification.read_at.is_(None),
            )
        )
        if not exists:
            db.add(
                Notification(
                    tenant_id=e.tenant_id,
                    user_id=u,
                    kind="inventory",
                    link=link,
                    title=f"Low stock: {item.name}",
                    body=f"On hand {on_hand} (reorder level {item.reorder_level})",
                )
            )


@consumer("invoice.issued", "notifications.invoice_issued")
def invoice_issued(db: Session, e: OutboxEvent) -> None:
    from manima.modules.invoicing.module import Invoice

    inv = db.get(Invoice, uuid.UUID(e.aggregate_id))
    if inv and inv.created_by:
        db.add(
            Notification(
                tenant_id=e.tenant_id,
                user_id=inv.created_by,
                kind="billing",
                link=f"/billing/invoices/{inv.id}",
                title=f"Invoice {inv.number} issued",
                body=f"₹{inv.grand_total} to {inv.recipient_name}",
            )
        )


# ---------------------------------------------------------------- processing
def process_event(event_id: uuid.UUID | str) -> None:
    """Run every consumer for one event, each in its own transaction, exactly-once in effect."""
    event_id = uuid.UUID(str(event_id))
    Session_ = session_factory()
    with platform_session_factory()() as db:
        e = db.get(OutboxEvent, event_id)
        if e is None:
            return
        handlers = CONSUMERS.get(e.event_type, [])
        tenant_id, payload_event = e.tenant_id, e
        db.expunge(payload_event)
    for name, fn in handlers:
        with Session_() as db:
            set_tenant(db, tenant_id)
            done = db.scalar(
                select(ProcessedEvent.event_id).where(
                    ProcessedEvent.consumer == name, ProcessedEvent.event_id == event_id
                )
            )
            if done:
                continue
            fn(db, payload_event)
            db.execute(
                insert(ProcessedEvent).values(consumer=name, event_id=event_id).on_conflict_do_nothing()
            )
            db.commit()


def relay_once(publish: Callable[[uuid.UUID], None] | None = None, batch: int = 100) -> int:
    """Publish a batch of pending outbox rows. Returns the number published."""
    publish = publish or process_event
    with platform_session_factory()() as db:
        rows = db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None), OutboxEvent.dead.is_(False))
            .order_by(OutboxEvent.occurred_at)
            .limit(batch)
            .with_for_update(skip_locked=True)
        ).all()
        n = 0
        for e in rows:
            try:
                publish(e.id)
                e.published_at = datetime.now(UTC)
                n += 1
            except Exception as exc:  # broker down or consumer failure: retry later, then dead-letter
                e.publish_attempts += 1
                e.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                if e.publish_attempts >= MAX_ATTEMPTS:
                    e.dead = True
                log.warning("outbox publish failed id=%s attempts=%s err=%s", e.id, e.publish_attempts, exc)
        db.commit()
        return n
