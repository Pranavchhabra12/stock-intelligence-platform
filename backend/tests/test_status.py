"""The status page: one call, read from the database, with a verdict per part."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from backend.core.config import Settings
from backend.services.status_service import StatusService, _age, _fresh

NOW = datetime(2026, 11, 22, 6, 0, tzinfo=UTC)


def test_freshness_rules() -> None:
    assert _fresh(NOW - timedelta(hours=2), NOW, timedelta(hours=3), timedelta(hours=9)) == "ok"
    assert _fresh(NOW - timedelta(hours=5), NOW, timedelta(hours=3), timedelta(hours=9)) == "warning"
    assert _fresh(NOW - timedelta(days=2), NOW, timedelta(hours=3), timedelta(hours=9)) == "failed"
    assert _fresh(None, NOW, timedelta(hours=3), timedelta(hours=9)) == "failed"
    assert _age(NOW - timedelta(minutes=20), NOW) == "20 min ago" and _age(None, NOW) == "never"


def facts(**over) -> dict:  # noqa: ANN003
    base = {
        "companies_listed": 2631, "companies_tracked": 5, "latest_price_date": date(2026, 11, 20),
        "stale_price_companies": 0, "latest_news_at": NOW - timedelta(hours=1), "news_last_24h": 40,
        "latest_filing_at": NOW - timedelta(hours=5), "latest_ai_at": NOW - timedelta(hours=2),
        "ai_rejected_7d": 0, "ai_saved_7d": 250, "latest_tone_day": date(2026, 11, 21), "documents_failed": 0,
        "fallback_rows_30d": 0,
        "results_fetch": {"last_success": NOW - timedelta(days=3), "failing": 0, "companies": 5},
        "jobs": {"scheduled_run": {"status": "completed", "finished_at": NOW - timedelta(hours=10), "error": None},
                 "feeds_run": {"status": "completed", "finished_at": NOW - timedelta(minutes=50), "error": None}},
        "last_ok": {"scheduled_run": NOW - timedelta(hours=10), "feeds_run": NOW - timedelta(minutes=50)},
    }
    return base | over


def service(key: str | None = "k") -> StatusService:
    return StatusService(None, Settings(_env_file=None, database_url="postgresql://x/y", gemini_api_key=key), now=NOW)


def test_all_ok_on_a_sunday_with_fridays_prices() -> None:
    checks = {c.name: c for c in service()._checks(facts())}
    assert all(c.status == "ok" for c in checks.values()), [(c.name, c.status) for c in checks.values()]
    assert "Latest close 20 Nov 2026" in checks["Prices and results"].detail


def test_problems_are_named() -> None:
    bad = facts(stale_price_companies=2, latest_news_at=NOW - timedelta(days=5), ai_rejected_7d=90,
                jobs={"scheduled_run": {"status": "completed_with_errors", "finished_at": NOW - timedelta(hours=10),
                                        "error": "news: gdelt refused"}},
                last_ok={"scheduled_run": NOW - timedelta(hours=10)})
    checks = {c.name: c for c in service()._checks(bad)}
    prices, daily = checks["Prices and results"], checks["Daily run (19:30 IST)"]
    assert prices.status == "warning" and "2 tracked companies" in prices.detail
    assert checks["News"].status == "failed"
    assert checks["AI (Gemini)"].status == "warning"
    assert daily.status == "warning" and "gdelt refused" in daily.detail
    assert checks["Hourly news run"].detail == "Hasn't run yet."
    no_key = {c.name: c for c in service(None)._checks(facts())}
    assert no_key["AI (Gemini)"].status == "warning" and "No Gemini key" in no_key["AI (Gemini)"].detail


def test_status_endpoint(client: TestClient, engine: Engine) -> None:
    body = client.get("/status").json()
    assert body["status"] in ("ok", "warning", "failed")
    names = [c["name"] for c in body["checks"]]
    assert names[0] == "Database" and body["checks"][0]["status"] == "ok"
    assert {"Prices and results", "News", "Exchange filings (BSE)", "AI (Gemini)"} <= set(names)
    assert body["companies"]["tracked"] == 5 and body["companies"]["cap"] == 25
    assert body["database_ms"] is not None


def test_results_check_appears_with_an_indianapi_key() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://x/y", gemini_api_key="k", indianapi_key="k")
    checks = {c.name: c for c in StatusService(None, settings, now=NOW)._checks(facts())}
    results = checks["Company results (IndianAPI)"]
    assert results.status == "ok" and "up to date for 5 companies" in results.detail
    failing = facts(results_fetch={"last_success": NOW - timedelta(days=3), "failing": 2, "companies": 4})
    assert {c.name: c for c in StatusService(None, settings, now=NOW)._checks(failing)}[
        "Company results (IndianAPI)"].status == "warning"

    waiting = facts(results_fetch={"last_success": None, "failing": 0, "companies": 0})
    first = {c.name: c for c in StatusService(None, settings, now=NOW)._checks(waiting)}["Company results (IndianAPI)"]
    assert first.status == "warning" and "waiting for its first fetch" in first.detail
