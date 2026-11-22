"""IndianAPI results: parsing, the request schedule that keeps inside 500 a month, and the
rule that IndianAPI's figures win over Yahoo's for the same period."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from backend.providers.market_data.base import FinancialPeriodData, ListingKey, ProviderError
from backend.providers.market_data.fallback import FallbackMarketDataProvider
from backend.providers.market_data.indianapi import IndianApiResultsAdapter, parse_period
from backend.services.market_data import MarketDataCollector
from backend.tests.fakes import FakeProvider
from backend.tests.test_collector import TODAY, clean_market_tables


def rows(**values: str) -> list[dict]:
    return [{"key": k, "value": v, "displayName": k} for k, v in values.items()]


def period(kind: str, end: str, length: str, inc: dict, bal: dict | None = None) -> dict:
    return {"Type": kind, "EndDate": end, "FiscalYear": "2027",
            "stockFinancialMap": {"INC": rows(periodLength=length, **inc), "BAL": rows(**(bal or {}))}}


BANK_YEAR = period("Annual", "2026-03-31", "12",
                   {"NetIncome": "76025.97", "DilutedEPSExcludingExtraOrdItems": "49.28",
                    "InterestIncomeBank": "348615.15", "Non-InterestIncomeBank": "146847.66"},
                   {"TotalEquity": "586059.47", "TotalCommonSharesOutstanding": "1539.34"})
QUARTER = period("Interim", "2026-09-30", "3",
                 {"TotalRevenue": "73188.00", "NetIncome": "13884.00", "DilutedEPSExcludingExtraOrdItems": "38.37"})


def test_parse_converts_crore_and_handles_banks() -> None:
    year = parse_period(BANK_YEAR)
    assert year.period_type == "annual" and year.period_end == date(2026, 3, 31)
    assert year.metrics["net_profit"] == Decimal("760259700000")          # ₹76,025.97 crore in rupees
    assert year.metrics["total_revenue"] == Decimal("4954628100000")      # interest + other income
    assert year.metrics["shares_outstanding"] == Decimal("15393400000")   # 1,539.34 crore shares
    assert year.metrics["eps"] == Decimal("49.28")                        # per share: not scaled
    quarter = parse_period(QUARTER)
    assert quarter.period_type == "quarterly" and quarter.metrics["total_revenue"] == Decimal("731880000000")
    assert "shareholders_equity" not in quarter.metrics                   # not reported: left out
    # Half-year and year-to-date figures don't compare with quarters; skip them.
    assert parse_period(period("Interim", "2026-09-30", "6", {"NetIncome": "1"})) is None


def adapter(handler) -> IndianApiResultsAdapter:  # noqa: ANN001
    return IndianApiResultsAdapter("k", client=httpx.Client(transport=httpx.MockTransport(handler)),
                                   sleep=lambda _: None)


def test_adapter_checks_it_found_the_right_company() -> None:
    seen = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["key"], seen["name"] = request.headers["x-api-key"], request.url.params["name"]
        return httpx.Response(200, json={"companyProfile": {"isInId": "INE040A01034"},
                                         "financials": [BANK_YEAR, QUARTER, QUARTER]})

    listing = ListingKey("NSE", "HDFCBANK", isin="INE040A01034")
    got = adapter(ok).get_financials(listing)
    assert seen == {"key": "k", "name": "HDFCBANK"}
    assert [(p.period_type, p.period_end) for p in got] == [("annual", date(2026, 3, 31)),
                                                            ("quarterly", date(2026, 9, 30))]
    with pytest.raises(ProviderError, match="different company"):
        adapter(ok).get_financials(ListingKey("NSE", "HDFCBANK", isin="INE002A01018"))
    with pytest.raises(ProviderError, match="limit"):
        adapter(lambda r: httpx.Response(429)).get_financials(listing)


class CountingProvider(FakeProvider):
    def __init__(self, *args, fail: bool = False, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.financial_calls = 0
        self.fail = fail

    def get_financials(self, listing: ListingKey) -> list[FinancialPeriodData]:
        self.financial_calls += 1
        if self.fail:
            raise ProviderError("indianapi request limit reached for now")
        return super().get_financials(listing)


Q2 = date(2026, 9, 30)


@pytest.fixture
def market(engine: Engine) -> Iterator[None]:
    clean_market_tables(engine)
    with engine.begin() as conn:
        conn.execute(text("delete from app.provider_fetches"))
    yield
    clean_market_tables(engine)
    with engine.begin() as conn:
        conn.execute(text("delete from app.provider_fetches"))


def company(engine: Engine, name: str) -> object:
    with engine.connect() as conn:
        return conn.execute(text("select company_id from app.companies where company_name = :n"), {"n": name}
                            ).scalar_one()


def collector(engine: Engine, rationed: CountingProvider, yahoo: FakeProvider, now: datetime) -> MarketDataCollector:
    chain = FallbackMarketDataProvider([yahoo], results_first=[rationed])
    return MarketDataCollector(engine, chain, backfill_years=1, today=TODAY, now=lambda: now)


def test_indianapi_is_asked_only_when_due(engine: Engine, market: None) -> None:
    cid = company(engine, "Reliance Industries")
    india = CountingProvider("indianapi", financials=[FinancialPeriodData("quarterly", Q2, {"net_profit": Decimal(5)})])
    yahoo = CountingProvider("yfinance", financials=[FinancialPeriodData("quarterly", Q2, {"net_profit": Decimal(4)})])
    start = datetime(2026, 11, 20, 14, tzinfo=UTC)

    collector(engine, india, yahoo, start).collect_company(cid)
    assert (india.financial_calls, yahoo.financial_calls) == (1, 0)        # first time: asked
    collector(engine, india, yahoo, start + timedelta(days=1)).collect_company(cid)
    assert (india.financial_calls, yahoo.financial_calls) == (1, 1)        # not due: Yahoo instead
    collector(engine, india, yahoo, start + timedelta(days=14)).collect_company(cid)
    assert india.financial_calls == 2                                      # two weeks on: asked again

    # Once the next quarter's results are expected, it's asked every two days instead.
    late = collector(engine, india, yahoo, start + timedelta(days=16))
    late.today = Q2 + timedelta(days=110)
    late.collect_company(cid)
    assert india.financial_calls == 3


def test_failures_count_and_untracked_companies_are_never_asked(engine: Engine, market: None) -> None:
    cid = company(engine, "Reliance Industries")
    broken = CountingProvider("indianapi", fail=True)
    yahoo = CountingProvider("yfinance", financials=[FinancialPeriodData("quarterly", Q2, {"net_profit": Decimal(4)})])
    now = datetime(2026, 11, 20, 14, tzinfo=UTC)
    result = collector(engine, broken, yahoo, now).collect_company(cid)
    assert result.periods_upserted == 1 and yahoo.financial_calls == 1     # Yahoo stepped in
    with engine.connect() as conn:
        fetch = conn.execute(text("select last_error, last_success_at, attempts from app.provider_fetches")
                             ).mappings().one()
    assert "limit" in fetch["last_error"] and fetch["last_success_at"] is None and fetch["attempts"] == 1
    collector(engine, broken, yahoo, now + timedelta(hours=6)).collect_company(cid)
    assert broken.financial_calls == 1                                     # a failure still waits its turn

    with engine.begin() as conn:
        conn.execute(text("update app.companies set is_tracked = false where company_id = :c"), {"c": cid})
    try:
        collector(engine, broken, yahoo, now + timedelta(days=30)).collect_company(cid)
        assert broken.financial_calls == 1                                 # not in Power BI: never asked
    finally:
        with engine.begin() as conn:
            conn.execute(text("update app.companies set is_tracked = true where company_id = :c"), {"c": cid})


def test_indianapi_figures_win_for_the_same_period(client: TestClient, engine: Engine, market: None) -> None:
    cid = company(engine, "Reliance Industries")
    india = CountingProvider("indianapi", financials=[
        FinancialPeriodData("quarterly", Q2, {"total_revenue": Decimal("3328610000000")})])
    yahoo = CountingProvider("yfinance", financials=[
        FinancialPeriodData("quarterly", Q2, {"total_revenue": Decimal("2500000000000")}),
        FinancialPeriodData("quarterly", date(2026, 6, 30), {"total_revenue": Decimal("2400000000000")})])
    now = datetime(2026, 11, 20, 14, tzinfo=UTC)
    collector(engine, india, yahoo, now).collect_company(cid)                         # IndianAPI
    collector(engine, india, yahoo, now + timedelta(days=1)).collect_company(cid)     # Yahoo, later
    body = client.get("/stocks/RELIANCE/financials").json()
    assert [(p["label"], p["metrics"]["total_revenue"]) for p in body["periods"]] == [
        ("Q2 FY2027", 3.32861e12),     # both have it: IndianAPI's figure
        ("Q1 FY2027", 2.4e12),         # only Yahoo has it
    ]
