"""Platform core tables: identity, tenancy, RBAC, registry/entitlements, billing, audit, outbox."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from manima.shared.db import SCHEMA, Base, Money, TenantMixin, TimestampMixin, uuid7

UUIDPK = mapped_column  # alias for readability


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


# ---------------------------------------------------------------- identity
class PlatformUser(TimestampMixin, Base):
    __tablename__ = "platform_users"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    mfa_required: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status in ('active','disabled')", name="status"),)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.platform_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


# ---------------------------------------------------------------- tenancy
class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = _pk()
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    industry_pack: Mapped[str] = mapped_column(String(40), default="distribution")
    status: Mapped[str] = mapped_column(String(20), default="active")
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)
    region: Mapped[str] = mapped_column(String(20), default="ap-south-1")
    closing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status in ('active','suspended','closing','closed')", name="status"),)


class TenantSettings(TimestampMixin, Base):
    """Company profile + preferences (CC-08). Tenant-owned (RLS)."""

    __tablename__ = "tenant_settings"
    __tenant_scoped__ = True
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[dict] = mapped_column(JSONB, default=dict)
    state_code: Mapped[str | None] = mapped_column(String(2))
    pan: Mapped[str | None] = mapped_column(String(10))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=4)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    time_zone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata")
    locale: Mapped[str] = mapped_column(String(10), default="en-IN")
    date_format: Mapped[str] = mapped_column(String(20), default="DD/MM/YYYY")
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_validity_days: Mapped[int] = mapped_column(Integer, default=15)
    discount_approval_limit: Mapped[Decimal] = mapped_column(Money, default=Decimal("10"))
    invoice_terms: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)


class TenantMembership(TimestampMixin, Base):
    __tablename__ = "tenant_memberships"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.platform_users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    title: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint("status in ('invited','active','removed')", name="status"),
    )


class Invitation(TimestampMixin, Base):
    __tablename__ = "invitations"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    name: Mapped[str | None] = mapped_column(String(120))
    role_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


# ---------------------------------------------------------------- rbac
class Permission(Base):
    __tablename__ = "permissions"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    module_key: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(10), default="tenant")  # tenant | platform
    description: Mapped[str] = mapped_column(String(200))
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(300))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_key: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.permissions.key"), primary_key=True)


class MemberRole(Base):
    __tablename__ = "member_roles"
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.tenant_memberships.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.roles.id", ondelete="CASCADE"), primary_key=True
    )


class PlatformRoleAssignment(Base):
    __tablename__ = "platform_role_assignments"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.platform_users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.roles.id", ondelete="CASCADE"), primary_key=True
    )


# ---------------------------------------------------------------- registry / entitlements
class Module(TimestampMixin, Base):
    __tablename__ = "modules"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))
    depends_on: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list)
    platform_state: Mapped[str] = mapped_column(String(20), default="available")
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        CheckConstraint(
            "platform_state in ('registered','available','deprecated','retired')", name="platform_state"
        ),
    )


class Feature(TimestampMixin, Base):
    """Feature + its platform flag (global enable, kill switch, rollout rule)."""

    __tablename__ = "features"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    module_key: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.modules.key"))
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    rule: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Plan(TimestampMixin, Base):
    __tablename__ = "plans"
    id: Mapped[uuid.UUID] = _pk()
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(300))
    price_monthly: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    max_users: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PlanEntitlement(Base):
    __tablename__ = "plan_entitlements"
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.plans.id", ondelete="CASCADE"), primary_key=True
    )
    feature_key: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.features.key"), primary_key=True)
    limits: Mapped[dict] = mapped_column(JSONB, default=dict)


class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.plans.id"))
    status: Mapped[str] = mapped_column(String(20), default="trialing")
    billing_cycle: Mapped[str] = mapped_column(String(10), default="monthly")
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "status in ('trialing','active','past_due','grace','suspended','cancelled')", name="status"
        ),
    )


class TenantModuleState(Base):
    __tablename__ = "tenant_module_states"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), primary_key=True)
    module_key: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.modules.key"), primary_key=True)
    state: Mapped[str] = mapped_column(String(20), default="disabled")
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(String(300))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("state in ('enabled','draining','read_only','disabled')", name="state"),
    )


class TenantFeatureOverride(Base):
    __tablename__ = "tenant_feature_overrides"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), primary_key=True)
    feature_key: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.features.key"), primary_key=True)
    effect: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(String(300))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("effect in ('grant','revoke')", name="effect"),)


# ---------------------------------------------------------------- audit, outbox, idempotency, notifications
class AuditEvent(Base):
    """Append-only. Tenant rows are RLS-protected; platform rows have tenant_id NULL."""

    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(20), default="user")
    actor_email: Mapped[str | None] = mapped_column(String(254))
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(40))
    # Python-side default: INSERT must not need RETURNING (RLS select policy hides platform rows).
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now(), index=True
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    aggregate_type: Mapped[str] = mapped_column(String(60))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    dead: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "occurred_at",
            postgresql_where=text("published_at is null and dead = false"),
        ),
    )


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    consumer: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __tenant_scoped__ = True
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(String(80), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notification(TenantMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.platform_users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(String(1000))
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanChange(Base):
    __tablename__ = "plan_changes"
    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.tenants.id"), index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.subscriptions.id"))
    from_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.plans.id"))
    to_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.plans.id"))
    status: Mapped[str] = mapped_column(String(20), default="requested")
    note: Mapped[str | None] = mapped_column(String(300))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("status in ('requested','approved','rejected')", name="status"),)
