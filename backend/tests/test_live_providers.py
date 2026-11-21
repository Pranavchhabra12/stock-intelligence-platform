"""Live checks against the real providers. Skipped unless RUN_LIVE_TESTS=1.

Run by the "Live data check" GitHub Actions workflow, not in normal CI, because
external services can be slow or down for reasons unrelated to our code.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

from backend.providers.market_data.base import ListingKey
from backend.providers.market_data.eodhd import EodhdMarketDataAdapter
from backend.providers.market_data.upstox import UpstoxMarketDataAdapter
from backend.providers.market_data.yahoo import YahooMarketDataAdapter

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call real APIs"),
]

RELIANCE_NSE = ListingKey("NSE", "RELIANCE", "INE002A01018", overrides={"yfinance": "RELIANCE.NS"})
RELIANCE_BSE = ListingKey("BSE", "RELIANCE", "INE002A01018", "500325")
END = date.today()
START = END - timedelta(days=14)


def test_yahoo_prices_and_financials() -> None:
    yahoo = YahooMarketDataAdapter()
    history = yahoo.get_price_history(RELIANCE_NSE, START, END)
    print(f"yahoo NSE: {len(history.bars)} bars, last {history.bars[-1] if history.bars else None}")
    assert history.bars

    periods = yahoo.get_financials(RELIANCE_NSE)
    quarterly = [p for p in periods if p.period_type == "quarterly"]
    print(f"yahoo financials: {len(periods)} periods; latest quarter {quarterly[-1] if quarterly else None}")
    assert any("total_revenue" in p.metrics for p in periods)


def test_upstox_prices_both_exchanges() -> None:
    upstox = UpstoxMarketDataAdapter()
    for listing in (RELIANCE_NSE, RELIANCE_BSE):
        history = upstox.get_price_history(listing, START, END)
        print(f"upstox {listing.exchange}: {len(history.bars)} bars")
        assert history.bars


def test_yahoo_and_upstox_agree() -> None:
    yahoo = {b.trade_date: b.close for b in YahooMarketDataAdapter().get_price_history(RELIANCE_NSE, START, END).bars}
    upstox = {b.trade_date: b.close for b in UpstoxMarketDataAdapter().get_price_history(RELIANCE_NSE, START, END).bars}
    common = sorted(set(yahoo) & set(upstox))
    for day in common:
        print(f"{day}: yahoo {yahoo[day]}  upstox {upstox[day]}")
    assert common
    for day in common:
        assert abs(yahoo[day] - upstox[day]) / yahoo[day] < 0.01, f"closes differ by over 1% on {day}"


@pytest.mark.skipif(not os.environ.get("EODHD_API_KEY"), reason="no EODHD_API_KEY")
def test_eodhd_prices() -> None:
    history = EodhdMarketDataAdapter(os.environ["EODHD_API_KEY"]).get_price_history(RELIANCE_NSE, START, END)
    print(f"eodhd: {len(history.bars)} bars")
    assert history.bars
