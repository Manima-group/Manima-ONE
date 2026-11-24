from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MANIMA_", env_file=".env", extra="ignore")

    environment: str = "local"
    # Runtime role: NOBYPASSRLS, subject to forced row-level security.
    database_url: str = "postgresql+psycopg://manima_app:manima_app@localhost:5432/manima"
    # Owner role: used only by Alembic migrations.
    # Platform role: BYPASSRLS. Used only by the outbox relay, workers, CLI and platform-admin
    # cross-tenant metadata reads. Tenant request paths never touch this engine.
    platform_database_url: str = "postgresql+psycopg://manima_platform:manima_platform@localhost:5432/manima"
    migration_database_url: str = "postgresql+psycopg://manima:manima@localhost:5432/manima"
    redis_url: str = "redis://localhost:6379/0"
    # When true, outbox events are dispatched in-process right after commit (tests / no worker).
    events_eager: bool = False

    session_cookie_name: str = "m1s"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]

    # Bootstrap super admin (created by `python -m manima.cli bootstrap`). Never hardcode in prod.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    invitation_ttl_days: int = 7
    idempotency_ttl_hours: int = 24

    @model_validator(mode="after")
    def _harden_non_local(self) -> "Settings":
        # Deployed environments serve HTTPS only: Secure cookie with the __Host- prefix (API_STANDARDS §2).
        if self.environment not in ("local", "test"):
            self.cookie_secure = True
            if not self.session_cookie_name.startswith("__Host-"):
                self.session_cookie_name = "__Host-m1s"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
