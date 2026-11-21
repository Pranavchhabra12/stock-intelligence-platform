"""Database engine and per-request connections (SQLAlchemy Core + psycopg 3)."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import Connection

from backend.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_size,
        pool_pre_ping=True,      # survive dropped pooler connections
        pool_recycle=1800,
        connect_args={
            "connect_timeout": 10,
            "application_name": "stock-intelligence-backend",
            # Server-side prepared statements break behind transaction-mode
            # poolers (Supavisor :6543). Disabling them is harmless elsewhere.
            "prepare_threshold": None,
        },
    )


def get_connection() -> Iterator[Connection]:
    """FastAPI dependency: one connection per request, returned to the pool after."""
    with get_engine().connect() as connection:
        yield connection
