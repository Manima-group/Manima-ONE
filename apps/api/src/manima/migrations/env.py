"""Alembic env: runs as the schema OWNER role (MANIMA_MIGRATION_DATABASE_URL), never the runtime role."""

from alembic import context
from sqlalchemy import create_engine, text

from manima.models import metadata
from manima.settings import get_settings

config = context.config


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or get_settings().migration_database_url
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("create schema if not exists app"))
        conn.commit()
        context.configure(
            connection=conn,
            target_metadata=metadata,
            include_schemas=True,
            version_table_schema="public",
            include_name=lambda name, type_, parent: type_ != "schema" or name == "app",
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().migration_database_url,
        target_metadata=metadata,
        literal_binds=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
