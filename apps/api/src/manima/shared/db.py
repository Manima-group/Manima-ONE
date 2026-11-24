"""Database engine, declarative base, UUIDv7 ids and tenant context (RLS).

Every transaction opened on a Session whose ``info['tenant_id']`` is set runs
``set_config('app.tenant_id', ..., true)`` so PostgreSQL forced RLS policies
see the active tenant. Without it, tenant tables return zero rows (fail-closed).
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    create_engine,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, declared_attr, mapped_column, sessionmaker

from manima.settings import get_settings

SCHEMA = "app"

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7 (time ordered). Python < 3.14 has no uuid.uuid7."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ((rand >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= rand & ((1 << 62) - 1)
    return uuid.UUID(int=value)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=convention)


Money = Numeric(18, 2)
Qty = Numeric(18, 3)
Rate = Numeric(7, 4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantMixin(TimestampMixin):
    """Standard columns for every tenant-owned table (SCHEMA_DESIGN conventions)."""

    __tenant_scoped__ = True

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenants.id"), nullable=False, index=True
        )

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


def tenant_tables() -> list[str]:
    out = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if getattr(cls, "__tenant_scoped__", False):
            out.append(cls.__tablename__)
    return sorted(set(out))


_engine = None
_SessionLocal: sessionmaker[Session] | None = None
_platform_engine = None
_PlatformSessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
    return _engine


def session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=True)
    return _SessionLocal


def platform_session_factory() -> sessionmaker[Session]:
    """Sessions on the BYPASSRLS platform role (relay, workers, CLI, platform metadata).

    Never use from tenant request handlers: tenant isolation there relies on forced RLS.
    """
    global _platform_engine, _PlatformSessionLocal
    if _PlatformSessionLocal is None:
        _platform_engine = create_engine(get_settings().platform_database_url, pool_pre_ping=True)
        _PlatformSessionLocal = sessionmaker(bind=_platform_engine, expire_on_commit=False, autoflush=True)
    return _PlatformSessionLocal


def reset_engine() -> None:
    global _engine, _SessionLocal, _platform_engine, _PlatformSessionLocal
    for e in (_engine, _platform_engine):
        if e is not None:
            e.dispose()
    _engine = _platform_engine = None
    _SessionLocal = _PlatformSessionLocal = None


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:
    _set_context(connection, session.info)


def _set_context(connection, info: dict) -> None:
    tid = info.get("tenant_id")
    connection.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tid) if tid else ""})


def set_tenant(session: Session, tenant_id: uuid.UUID | None) -> None:
    """Bind the session (current and future transactions) to a tenant. None = no tenant rows visible."""
    session.info["tenant_id"] = tenant_id
    if session.in_transaction():
        _set_context(session.connection(), session.info)


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def to_decimal(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def tenant_args(*extra):
    """__table_args__ for tenant tables: unique(tenant_id, id) enables composite FKs."""
    from sqlalchemy import UniqueConstraint

    return (UniqueConstraint("tenant_id", "id", name=None), *extra)


def tfk(column: str, table: str, ondelete: str | None = None):
    """Composite tenant FK: (tenant_id, column) -> table(tenant_id, id). Blocks cross-tenant links."""
    from sqlalchemy import ForeignKeyConstraint

    return ForeignKeyConstraint(
        ["tenant_id", column], [f"{SCHEMA}.{table}.tenant_id", f"{SCHEMA}.{table}.id"], ondelete=ondelete
    )
