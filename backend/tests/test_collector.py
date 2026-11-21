"""Market-data collection against a real database, with fake providers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from backend.providers.market_data.base import CompanyProfile, CorporateAction, FinancialPeriodData
from backend.providers.market_data.fallback import FallbackMarketDataProvider
from backend.services.market_data import MarketDataCollector
from backend.tests.fakes import FakeProvider

TODAY = date(2026, 11, 20)  # a Friday


def clean_market_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "delete from app.financial_metrics; delete from app.financial_periods; "
            "delete from app.corporate_actions; delete from app.daily_prices; "
            "update app.companies set sector = null, industry = null, website = null, description = null;"
        ))


@pytest.fixture
def clean(engine: Engine) -> Iterator[None]:
    clean_market_tables(engine)
    yield
    clean_market_tables(engine)


def company_id(engine: Engine, name: str) -> UUID:
    with engine.connect() as conn:
        return conn.execute(
            text("select company_id from app.companies where company_name = :n"), {"n": name}
        ).scalar_one()


def price_rows(engine: Engine, exchange: str = "NSE") -> list:
    with engine.connect() as conn:
        return conn.execute(text(
            """
            select p.trade_date, s.source_code, p.price_basis
            from app.daily_prices p
            join app.company_listings l using (listing_id)
            join app.data_sources s on s.source_id = p.source_id
            where l.symbol = 'RELIANCE' and l.exchange = :ex order by p.trade_date
            """
        ), {"ex": exchange}).all()


def collector(engine: Engine, *providers: FakeProvider, years: int = 1) -> MarketDataCollector:
    return MarketDataCollector(engine, FallbackMarketDataProvider(list(providers)), backfill_years=years, today=TODAY)


def test_first_run_backfills_both_listings(engine: Engine, clean: None) -> None:
    result = collector(engine, FakeProvider()).collect_company(company_id(engine, "Reliance Industries"))
    assert result.status == "completed", result.errors
    nse, bse = price_rows(engine, "NSE"), price_rows(engine, "BSE")
    assert len(nse) == len(bse) > 250  # about a year of weekdays
    assert result.price_sources == {"NSE:RELIANCE": "yfinance", "BSE:RELIANCE": "yfinance"}


def test_second_run_is_incremental_and_adds_no_duplicates(engine: Engine, clean: None) -> None:
    cid = company_id(engine, "Reliance Industries")
    collector(engine, FakeProvider()).collect_company(cid)
    before = len(price_rows(engine))

    provider = FakeProvider()
    later = MarketDataCollector(engine, provider, backfill_years=1, today=date(2026, 11, 24))
    result = later.collect_company(cid)
    assert result.status == "completed"
    assert provider.price_calls[0][1] == date(2026, 11, 21)   # starts the day after the last stored row
    assert len(price_rows(engine)) == before + 2              # Mon 23 and Tue 24 only


def test_fallback_provider_fills_in_and_is_recorded(engine: Engine, clean: None) -> None:
    result = collector(engine, FakeProvider("yfinance", fail_prices=True), FakeProvider("upstox", "unknown")) \
        .collect_company(company_id(engine, "Reliance Industries"))
    assert result.status == "completed"
    rows = price_rows(engine)
    assert {r.source_code for r in rows} == {"upstox"}
    assert {r.price_basis for r in rows} == {"unknown"}


def test_all_providers_down_is_reported_not_hidden(engine: Engine, clean: None) -> None:
    result = collector(engine, FakeProvider("yfinance", fail_prices=True), FakeProvider("upstox", fail_prices=True)) \
        .collect_company(company_id(engine, "Reliance Industries"))
    assert result.status == "failed"
    assert any("all price providers failed" in e for e in result.errors)
    assert price_rows(engine) == []


def test_new_split_triggers_full_refetch(engine: Engine, clean: None) -> None:
    cid = company_id(engine, "Reliance Industries")
    collector(engine, FakeProvider()).collect_company(cid)

    provider = FakeProvider(actions=[CorporateAction(date(2026, 6, 1), "split", ratio=Decimal("2"))])
    result = MarketDataCollector(engine, provider, backfill_years=1, today=TODAY).collect_company(cid)
    assert result.actions_new == 2                     # one per listing (NSE and BSE)
    assert set(result.full_refetch) == {"NSE:RELIANCE", "BSE:RELIANCE"}
    assert provider.price_calls[0][1] < date(2026, 1, 1)  # went back to the start, not just the last day

    # Seen again: not new, so no second refetch.
    again = MarketDataCollector(engine, provider, backfill_years=1, today=TODAY).collect_company(cid)
    assert again.actions_new == 0 and again.full_refetch == []


def test_financials_and_profile(engine: Engine, clean: None) -> None:
    cid = company_id(engine, "Infosys")
    provider = FakeProvider(
        financials=[FinancialPeriodData("quarterly", date(2026, 9, 30),
                                        {"total_revenue": Decimal("100"), "net_profit": Decimal("20")})],
        profile=CompanyProfile(sector="Technology", industry="IT Services"),
    )
    result = collector(engine, provider).collect_company(cid)
    assert result.periods_upserted == 1
    with engine.connect() as conn:
        period = conn.execute(text(
            "select fiscal_year, fiscal_quarter, consolidation from app.financial_periods where company_id = :c"
        ), {"c": cid}).one()
        assert tuple(period) == (2027, 2, "unknown")  # Jul-Sep 2026 is Q2 of FY2027
        assert conn.execute(text("select sector from app.companies where company_id = :c"),
                            {"c": cid}).scalar() == "Technology"

    # The profile only fills blanks; it never overwrites.
    collector(engine, FakeProvider(profile=CompanyProfile(sector="Other"))).collect_company(cid)
    with engine.connect() as conn:
        assert conn.execute(text("select sector from app.companies where company_id = :c"),
                            {"c": cid}).scalar() == "Technology"


def test_derived_metrics_cannot_be_stored(engine: Engine, clean: None) -> None:
    cid = company_id(engine, "Infosys")
    collector(engine, FakeProvider(financials=[FinancialPeriodData("annual", date(2026, 3, 31),
                                                                   {"eps": Decimal("60")})])).collect_company(cid)
    with engine.connect() as conn, pytest.raises(DBAPIError, match="derived"):
        pid = conn.execute(text("select period_id from app.financial_periods where company_id = :c"),
                           {"c": cid}).scalar_one()
        conn.execute(text("insert into app.financial_metrics values (:p, 'pe_ratio', 25)"), {"p": pid})


def test_unregistered_source_fails_clearly(engine: Engine, clean: None) -> None:
    result = collector(engine, FakeProvider("nosuchsource")).collect_company(company_id(engine, "Infosys"))
    assert result.status == "failed"
    assert "not registered" in result.errors[0]
