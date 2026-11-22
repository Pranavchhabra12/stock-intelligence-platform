"""Migrations run from empty to head, back to base, and up again."""

from __future__ import annotations

from alembic import command
from sqlalchemy import create_engine, text

from backend.tests.conftest import _recreate_database, alembic_config

APP_TABLES = {
    # Phase 1
    "data_sources", "companies", "company_listings", "company_aliases", "listing_provider_ids",
    # Phase 2
    "daily_prices", "corporate_actions", "metric_definitions", "financial_periods", "financial_metrics",
    # Phase 3
    "news_articles", "article_companies", "company_documents", "document_chunks",
    # Phase 4
    "ai_analyses", "sentiment_history",
    # Phase 5
    "collection_jobs",
    # Phase 8: rationed providers (IndianAPI results)
    "provider_fetches",
}


def _tables(url: str) -> dict[str, bool]:
    eng = create_engine(url)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                """
                select c.relname, c.relrowsecurity
                from pg_class c join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'app' and c.relkind = 'r' and c.relname <> 'alembic_version'
                """
            )
        )
        result = {r[0]: r[1] for r in rows}
    eng.dispose()
    return result


def test_round_trip() -> None:
    url = _recreate_database("sip_pytest_migrations")
    cfg = alembic_config(url)

    command.upgrade(cfg, "head")
    tables = _tables(url)
    assert set(tables) == APP_TABLES
    assert all(tables.values()), "row level security must be enabled on every app table"

    command.downgrade(cfg, "base")
    assert _tables(url) == {}

    command.upgrade(cfg, "head")
    assert set(_tables(url)) == APP_TABLES
