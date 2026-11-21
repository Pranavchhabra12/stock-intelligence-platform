"""Helpers for database connection strings."""

from __future__ import annotations


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy URL that uses the psycopg 3 driver.

    Supabase and most hosts hand out ``postgres://`` or ``postgresql://`` URLs.
    SQLAlchemy needs the driver named explicitly, so we add ``+psycopg``.
    """
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url
