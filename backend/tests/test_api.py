"""API acceptance tests for Phase 1."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core.middleware import FixedWindowRateLimiter
from backend.services.company_service import normalize_query


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}
    assert r.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("RELIANCE", "Reliance Industries"),
        ("reliance", "Reliance Industries"),
        ("RIL", "Reliance Industries"),
        ("500325", "Reliance Industries"),
        ("INE002A01018", "Reliance Industries"),
        ("relaince", "Reliance Industries"),        # typo
        ("tcs", "Tata Consultancy Services"),
        ("tata consultancy", "Tata Consultancy Services"),
        ("infy", "Infosys"),
        ("hdfc bank", "HDFC Bank"),
        ("ICICI", "ICICI Bank"),
    ],
)
def test_search_finds_the_right_company_first(client: TestClient, query: str, expected: str) -> None:
    r = client.get("/stocks/search", params={"q": query})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["results"][0]["company_name"] == expected


def test_search_returns_each_company_once_with_both_listings(client: TestClient) -> None:
    body = client.get("/stocks/search", params={"q": "RELIANCE"}).json()
    names = [res["company_name"] for res in body["results"]]
    assert len(names) == len(set(names))
    exchanges = {lst["exchange"] for lst in body["results"][0]["listings"]}
    assert exchanges == {"NSE", "BSE"}
    assert body["results"][0]["score"] == 1.0


def test_search_with_no_match_is_an_empty_list(client: TestClient) -> None:
    r = client.get("/stocks/search", params={"q": "zzqqxx"})
    assert r.status_code == 200
    assert r.json() == {"query": "zzqqxx", "count": 0, "results": []}


@pytest.mark.parametrize("query", ["x", "!!", "a" * 65])
def test_invalid_search_input_returns_422(client: TestClient, query: str) -> None:
    r = client.get("/stocks/search", params={"q": query})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_nse_and_bse_lookups_return_the_same_company(client: TestClient) -> None:
    nse = client.get("/stocks/RELIANCE").json()
    bse = client.get("/stocks/500325", params={"exchange": "BSE"}).json()
    assert nse["company_id"] == bse["company_id"]
    assert {lst["exchange"] for lst in nse["listings"]} == {"NSE", "BSE"}
    assert "RIL" in nse["aliases"]


def test_lookup_without_exchange_falls_back_to_bse_code(client: TestClient) -> None:
    r = client.get("/stocks/532540")
    assert r.status_code == 200
    assert r.json()["company_name"] == "Tata Consultancy Services"


def test_unknown_ticker_returns_404(client: TestClient) -> None:
    r = client.get("/stocks/NOSUCHCO")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found"
    assert err["request_id"]


def test_invalid_ticker_characters_return_422(client: TestClient) -> None:
    assert client.get("/stocks/bad%20ticker").status_code == 422


def test_errors_never_leak_connection_details(client: TestClient, database_url: str) -> None:
    for path in ("/stocks/NOSUCHCO", "/stocks/search?q=x"):
        assert "postgres" not in client.get(path).text.lower()


def test_normalize_query_matches_database_rule() -> None:
    assert normalize_query("  Tata-Consultancy  Services! ") == "tata consultancy services"


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = FixedWindowRateLimiter(limit_per_minute=3)
    results = [limiter.check("1.2.3.4")[0] for _ in range(4)]
    assert results == [True, True, True, False]
    assert limiter.check("5.6.7.8")[0] is True
