"""API tests for prices and financials."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from backend.providers.market_data.base import FinancialPeriodData
from backend.providers.market_data.fallback import FallbackMarketDataProvider
from backend.services.market_data import MarketDataCollector
from backend.tests.fakes import FakeProvider
from backend.tests.test_collector import TODAY, clean_market_tables


@pytest.fixture(scope="module")
def collected(engine: Engine) -> Iterator[None]:
    clean_market_tables(engine)
    with engine.connect() as conn:
        cid = conn.execute(text("select company_id from app.companies where company_name = 'Reliance Industries'")
                           ).scalar_one()
    provider = FakeProvider(financials=[
        FinancialPeriodData("quarterly", date(2026, 9, 30), {"total_revenue": Decimal("2500000000000"),
                                                             "net_profit": Decimal("190000000000")}),
        FinancialPeriodData("quarterly", date(2026, 6, 30), {"total_revenue": Decimal("2400000000000")}),
        FinancialPeriodData("annual", date(2026, 3, 31), {"eps": Decimal("51.5")}),
    ])
    MarketDataCollector(engine, FallbackMarketDataProvider([provider]), backfill_years=1, today=TODAY) \
        .collect_company(cid)
    yield
    clean_market_tables(engine)


def test_prices_default_to_nse(client: TestClient, collected: None) -> None:
    r = client.get("/stocks/RELIANCE/prices", params={"start": "2026-11-16", "end": "2026-11-20"})
    assert r.status_code == 200
    body = r.json()
    assert body["listing"]["exchange"] == "NSE"
    assert body["count"] == 5
    assert body["price_basis"] == "split_adjusted"
    assert [s["code"] for s in body["sources"]] == ["yfinance"]
    assert body["sources"][0]["attribution"].startswith("Market data: Yahoo Finance")
    assert body["prices"][0]["trade_date"] == "2026-11-16"
    assert {p["source"] for p in body["prices"]} == {"yfinance"}
    assert "not investment advice" in body["data_note"]


def test_prices_for_bse_listing(client: TestClient, collected: None) -> None:
    body = client.get("/stocks/500325/prices",
                      params={"exchange": "BSE", "start": "2026-11-16", "end": "2026-11-20"}).json()
    assert body["listing"]["exchange"] == "BSE" and body["listing"]["exchange_code"] == "500325"
    assert body["count"] == 5


def test_prices_with_no_rows_in_range(client: TestClient, collected: None) -> None:
    body = client.get("/stocks/RELIANCE/prices", params={"start": "2010-01-01", "end": "2010-01-31"}).json()
    assert body["count"] == 0 and body["price_basis"] is None and body["sources"] == []


@pytest.mark.parametrize("params", [{"start": "2026-11-20", "end": "2026-11-01"},
                                    {"start": "2000-01-01", "end": "2026-01-01"}])
def test_invalid_price_ranges(client: TestClient, params: dict) -> None:
    r = client.get("/stocks/RELIANCE/prices", params=params)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_financials_quarterly(client: TestClient, collected: None) -> None:
    body = client.get("/stocks/RELIANCE/financials").json()
    assert [p["label"] for p in body["periods"]] == ["Q2 FY2027", "Q1 FY2027"]
    latest = body["periods"][0]["metrics"]
    assert latest["total_revenue"] == 2.5e12
    assert latest["eps"] is None                        # not reported: null, never guessed
    assert set(latest) == set(body["metric_definitions"])
    assert "pe_ratio" not in body["metric_definitions"]  # derived metrics are not stored or served here


def test_financials_annual(client: TestClient, collected: None) -> None:
    body = client.get("/stocks/RELIANCE/financials", params={"period_type": "annual"}).json()
    assert [p["label"] for p in body["periods"]] == ["FY2026"]
    assert body["periods"][0]["fiscal_quarter"] is None


def test_unknown_ticker_404s(client: TestClient) -> None:
    assert client.get("/stocks/NOSUCHCO/prices").status_code == 404
    assert client.get("/stocks/NOSUCHCO/financials").status_code == 404
