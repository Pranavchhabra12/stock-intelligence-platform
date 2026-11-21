"""Provider adapters and the fallback chain, with no network access."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx
import pandas as pd
import pytest

from backend.providers.market_data.base import (
    ListingKey,
    NotSupportedError,
    PriceHistory,
    ProviderError,
    ProviderUnavailableError,
)
from backend.providers.market_data.eodhd import EodhdMarketDataAdapter
from backend.providers.market_data.fallback import FallbackMarketDataProvider
from backend.providers.market_data.upstox import UpstoxMarketDataAdapter
from backend.providers.market_data.yahoo import YahooMarketDataAdapter
from backend.tests.fakes import FakeProvider

NSE = ListingKey("NSE", "RELIANCE", "INE002A01018")
BSE = ListingKey("BSE", "RELIANCE", "INE002A01018", "500325")
NO_SLEEP = lambda _s: None  # noqa: E731


# ---------------- Yahoo ----------------

class FakeTicker:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0
        idx = pd.DatetimeIndex(["2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]).tz_localize("Asia/Kolkata")
        self._history = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, float("nan")],
                "High": [105.0, 99.0, 106.0, 110.0],      # row 2: high < low -> skipped
                "Low": [99.0, 100.0, 101.0, 100.0],
                "Close": [104.0, 100.5, 105.123456, 108.0],
                "Adj Close": [103.0, 100.0, 104.0, 107.0],
                "Volume": [1000, 2000, 3000, 4000],
            },
            index=idx,
        )
        q = pd.to_datetime(["2026-09-30", "2026-06-30"])
        self.quarterly_income_stmt = pd.DataFrame(
            {q[0]: [1000.0, 200.0, 15.5], q[1]: [900.0, float("nan"), 14.0]},
            index=["Total Revenue", "Net Income", "Basic EPS"],
        )
        self.quarterly_balance_sheet = pd.DataFrame(
            {q[0]: [5000.0, 1300.0]}, index=["Stockholders Equity", "Ordinary Shares Number"]
        )
        self.income_stmt = pd.DataFrame()
        self.balance_sheet = pd.DataFrame()
        self.dividends = pd.Series([5.5], index=pd.DatetimeIndex(["2026-08-14"]).tz_localize("Asia/Kolkata"))
        self.splits = pd.Series([2.0], index=pd.DatetimeIndex(["2024-10-28"]).tz_localize("Asia/Kolkata"))
        self.info = {"sector": "Energy", "industry": "Oil & Gas", "website": "https://example.com"}

    def history(self, **_kwargs):  # noqa: ANN003
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("temporary failure")
        return self._history


def yahoo(ticker: FakeTicker, attempts: int = 3) -> YahooMarketDataAdapter:
    return YahooMarketDataAdapter(min_interval_seconds=0, max_attempts=attempts,
                                  ticker_factory=lambda _s: ticker, sleep=NO_SLEEP)


def test_yahoo_symbols() -> None:
    adapter = yahoo(FakeTicker())
    assert adapter.symbol_for(NSE) == "RELIANCE.NS"
    assert adapter.symbol_for(BSE) == "RELIANCE.BO"
    assert adapter.symbol_for(ListingKey("NSE", "M&M", overrides={"yfinance": "M&M.NS"})) == "M&M.NS"


def test_yahoo_prices_skip_invalid_rows_and_round() -> None:
    history = yahoo(FakeTicker()).get_price_history(NSE, date(2026, 11, 17), date(2026, 11, 20))
    assert history.source_code == "yfinance" and history.price_basis == "split_adjusted"
    assert [b.trade_date for b in history.bars] == [date(2026, 11, 17), date(2026, 11, 19)]
    assert history.bars[1].close == Decimal("105.1235")


def test_yahoo_retries_then_succeeds() -> None:
    ticker = FakeTicker(fail_times=2)
    history = yahoo(ticker).get_price_history(NSE, date(2026, 11, 17), date(2026, 11, 20))
    assert ticker.calls == 3 and history.bars


def test_yahoo_gives_up_after_max_attempts() -> None:
    with pytest.raises(ProviderUnavailableError):
        yahoo(FakeTicker(fail_times=5), attempts=2).get_price_history(NSE, date(2026, 11, 17), date(2026, 11, 20))


class YFPricesMissingError(Exception):
    """Same name as yfinance's 'no prices in this range' error."""


def test_yahoo_no_prices_in_range_is_empty_not_an_error() -> None:
    ticker = FakeTicker()
    ticker.history = lambda **_k: (_ for _ in ()).throw(YFPricesMissingError("no price data"))  # type: ignore[method-assign]
    assert yahoo(ticker).get_price_history(NSE, date(2026, 11, 21), date(2026, 11, 22)).bars == []


def test_yahoo_network_failure_is_raised_not_hidden() -> None:
    ticker = FakeTicker()
    ticker.history = lambda **_k: (_ for _ in ()).throw(RuntimeError("no timezone found"))  # type: ignore[method-assign]
    with pytest.raises(ProviderUnavailableError):
        yahoo(ticker, attempts=2).get_price_history(NSE, date(2026, 11, 17), date(2026, 11, 20))


def test_yahoo_no_statements_at_all_is_a_failure() -> None:
    ticker = FakeTicker()
    ticker.quarterly_income_stmt = ticker.quarterly_balance_sheet = pd.DataFrame()
    with pytest.raises(ProviderUnavailableError):
        yahoo(ticker).get_financials(NSE)


def test_yahoo_requests_errors_to_be_raised() -> None:
    seen = {}
    ticker = FakeTicker()
    original = ticker.history

    def spy(**kwargs):  # noqa: ANN003
        seen.update(kwargs)
        return original(**kwargs)

    ticker.history = spy  # type: ignore[method-assign]
    yahoo(ticker).get_price_history(NSE, date(2026, 11, 17), date(2026, 11, 20))
    assert seen["raise_errors"] is True and seen["auto_adjust"] is False


def test_yahoo_financials_actions_profile() -> None:
    adapter = yahoo(FakeTicker())
    periods = {p.period_end: p for p in adapter.get_financials(NSE)}
    sep = periods[date(2026, 9, 30)].metrics
    assert sep == {"total_revenue": Decimal("1000.0"), "net_profit": Decimal("200.0"), "eps": Decimal("15.5"),
                   "shareholders_equity": Decimal("5000.0"), "shares_outstanding": Decimal("1300.0")}
    assert "net_profit" not in periods[date(2026, 6, 30)].metrics  # NaN is left out, never guessed

    actions = adapter.get_corporate_actions(NSE)
    assert {(a.action_type, a.ex_date) for a in actions} == {("dividend", date(2026, 8, 14)),
                                                             ("split", date(2024, 10, 28))}
    assert adapter.get_profile(NSE).sector == "Energy"


# ---------------- Upstox ----------------

def upstox_with(handler) -> UpstoxMarketDataAdapter:  # noqa: ANN001
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return UpstoxMarketDataAdapter(client=client, min_interval_seconds=0, sleep=NO_SLEEP)


def test_upstox_builds_isin_key_and_parses_candles() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"status": "success", "data": {"candles": [
            ["2026-11-20T00:00:00+05:30", 1500.0, 1520.0, 1490.0, 1510.0, 123456, 0],
            ["2026-11-19T00:00:00+05:30", 1480.0, 1470.0, 1490.0, 1485.0, 1000, 0],  # invalid: high < low
        ]}})

    history = upstox_with(handler).get_price_history(NSE, date(2026, 11, 19), date(2026, 11, 20))
    assert seen == ["/v3/historical-candle/NSE_EQ%7CINE002A01018/days/1/2026-11-20/2026-11-19"]
    assert history.source_code == "upstox" and history.price_basis == "unknown"
    assert [b.trade_date for b in history.bars] == [date(2026, 11, 20)]


def test_upstox_requests_in_yearly_chunks() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"status": "success", "data": {"candles": []}})

    upstox_with(handler).get_price_history(NSE, date(2024, 1, 1), date(2026, 6, 30))
    assert len(calls) == 3


def test_upstox_retries_server_errors_but_not_bad_requests() -> None:
    responses = iter([httpx.Response(503), httpx.Response(200, json={"status": "success", "data": {"candles": []}})])
    assert upstox_with(lambda _r: next(responses)).get_price_history(
        NSE, date(2026, 11, 19), date(2026, 11, 20)).bars == []

    calls = []

    def bad(_r: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"status": "error"})

    with pytest.raises(ProviderError):
        upstox_with(bad).get_price_history(NSE, date(2026, 11, 19), date(2026, 11, 20))
    assert len(calls) == 1


def test_upstox_needs_isin() -> None:
    with pytest.raises(NotSupportedError):
        upstox_with(lambda _r: httpx.Response(200)).get_price_history(
            ListingKey("NSE", "XYZ"), date(2026, 1, 1), date(2026, 1, 2))


# ---------------- EODHD ----------------

def test_eodhd_clamps_to_free_plan_year_and_parses() -> None:
    params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        params.update(dict(request.url.params))
        assert request.url.path == "/api/eod/RELIANCE.NSE"
        return httpx.Response(200, content=json.dumps([
            {"date": "2026-11-20", "open": 10, "high": 12, "low": 9, "close": 11, "adjusted_close": 11, "volume": 5},
        ]))

    adapter = EodhdMarketDataAdapter("key", client=httpx.Client(transport=httpx.MockTransport(handler)),
                                     sleep=NO_SLEEP, today=date(2026, 11, 20))
    history = adapter.get_price_history(NSE, date(2020, 1, 1), date(2026, 11, 20))
    assert params["from"] == "2025-11-20" and params["api_token"] == "key"
    assert len(history.bars) == 1
    with pytest.raises(NotSupportedError):
        adapter.get_price_history(BSE, date(2026, 11, 1), date(2026, 11, 20))


# ---------------- Fallback chain ----------------

def test_fallback_uses_next_provider_when_primary_fails() -> None:
    chain = FallbackMarketDataProvider([FakeProvider("yfinance", fail_prices=True), FakeProvider("upstox", "unknown")])
    history = chain.get_price_history(NSE, date(2026, 11, 16), date(2026, 11, 20))
    assert history.source_code == "upstox" and len(history.bars) == 5


def test_fallback_uses_next_provider_when_primary_is_empty() -> None:
    chain = FallbackMarketDataProvider([FakeProvider("yfinance", empty_prices=True), FakeProvider("upstox")])
    assert chain.get_price_history(NSE, date(2026, 11, 16), date(2026, 11, 20)).source_code == "upstox"


def test_fallback_returns_empty_when_everyone_answers_empty() -> None:
    chain = FallbackMarketDataProvider([FakeProvider("yfinance", empty_prices=True),
                                        FakeProvider("upstox", empty_prices=True)])
    assert chain.get_price_history(NSE, date(2026, 11, 21), date(2026, 11, 22)) == PriceHistory("yfinance",
                                                                                                "split_adjusted", [])


def test_fallback_raises_when_every_provider_fails() -> None:
    chain = FallbackMarketDataProvider([FakeProvider("yfinance", fail_prices=True),
                                        FakeProvider("upstox", fail_prices=True)])
    with pytest.raises(ProviderError, match="all price providers failed"):
        chain.get_price_history(NSE, date(2026, 11, 16), date(2026, 11, 20))


def test_fallback_skips_providers_without_fundamentals() -> None:
    chain = FallbackMarketDataProvider([FakeProvider("upstox", supports_fundamentals=False), FakeProvider("yfinance")])
    source, _ = chain.first_available("financials", lambda p: p.get_financials(NSE))
    assert source == "yfinance"
