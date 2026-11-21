"""Alembic environment.

Migrations are plain SQL (``op.execute``); there is no ORM metadata and no
autogenerate. The connection URL is read from the environment, never from
alembic.ini, so no credentials live in the repository.

URL precedence:
1. ``config.attributes["url"]`` (set programmatically, e.g. by tests)
2. ``DATABASE_MIGRATION_URL``
3. ``DATABASE_URL``
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from backend.database.urls import normalize_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

VERSION_TABLE_SCHEMA = "app"


def _database_url() -> str:
    url = (
        config.attributes.get("url")
        or os.environ.get("DATABASE_MIGRATION_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        raise RuntimeError(
            "Set DATABASE_MIGRATION_URL or DATABASE_URL before running migrations."
        )
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        literal_binds=True,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        # The version table lives in the private `app` schema (not exposed by
        # Supabase's Data API), so the schema must exist before Alembic starts.
        connection.execute(text("create schema if not exists app"))
        connection.commit()

        context.configure(
            connection=connection,
            version_table_schema=VERSION_TABLE_SCHEMA,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
