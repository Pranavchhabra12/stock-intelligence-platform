"""EODHD end-of-day prices. Last-resort fallback, used only if EODHD_API_KEY is set.

The free plan allows 20 API calls a day and only the last year of history, and
covers NSE tickers as SYMBOL.NSE. The free plan's adjustment basis is not stated
for the `close` field here, so rows are stored with `price_basis = "unknown"`.

Docs: https://eodhd.com/financial-apis/quick-start-with-our-financial-data-apis
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta

import httpx

from backend.providers.market_data.base import (
    ListingKey,
    MarketDataProvider,
    NotSupportedError,
    PriceHistory,
    ProviderError,
)
from backend.providers.market_data.validation import make_bar
from backend.providers.retry import CallPolicy

BASE_URL = "https://eodhd.com/api/eod"
FREE_PLAN_HISTORY_DAYS = 365


class EodhdMarketDataAdapter(MarketDataProvider):
    source_code = "eodhd"
    price_basis = "unknown"

    def __init__(
        self, api_key: str, client: httpx.Client | None = None, max_attempts: int = 2,
        sleep: Callable[[float], None] = time.sleep, today: date | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=20)
        self.policy = CallPolicy(self.source_code, 1.0, max_attempts, sleep)
        self.today = today

    def symbol_for(self, listing: ListingKey) -> str:
        if self.source_code in listing.overrides:
            return listing.overrides[self.source_code]
        if listing.exchange != "NSE":
            raise NotSupportedError("eodhd adapter only maps NSE listings")
        return f"{listing.symbol}.NSE"

    def _fetch(self, symbol: str, start: date, end: date) -> list[dict]:
        response = self.client.get(
            f"{BASE_URL}/{symbol}",
            params={"api_token": self.api_key, "fmt": "json", "period": "d",
                    "from": start.isoformat(), "to": end.isoformat()},
        )
        if response.status_code in (401, 402, 403, 404):
            raise ProviderError(f"eodhd refused {symbol}: HTTP {response.status_code}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ProviderError(f"eodhd unexpected response for {symbol}")
        return data

    def get_price_history(self, listing: ListingKey, start: date, end: date) -> PriceHistory:
        symbol = self.symbol_for(listing)
        # The free plan only serves the last year; don't spend calls on more.
        earliest = (self.today or date.today()) - timedelta(days=FREE_PLAN_HISTORY_DAYS)
        start = max(start, earliest)
        if start > end:
            return PriceHistory(self.source_code, self.price_basis, [])
        rows = self.policy.call("eod", symbol, lambda: self._fetch(symbol, start, end))
        bars = []
        for row in rows:
            try:
                day = date.fromisoformat(row["date"])
            except (KeyError, ValueError):
                continue
            if start <= day <= end:
                bar = make_bar(day, row.get("open"), row.get("high"), row.get("low"), row.get("close"),
                               row.get("volume"), row.get("adjusted_close"))
                if bar:
                    bars.append(bar)
        return PriceHistory(self.source_code, self.price_basis, bars)
