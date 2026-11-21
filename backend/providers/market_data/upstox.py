"""Upstox historical candles. First fallback for prices.

The Historical Candle Data V3 endpoint is public (no account or token needed)
and is keyed by exchange segment + ISIN, e.g. NSE_EQ|INE002A01018. Upstox does
not state how its daily candles are adjusted, so rows are stored with
`price_basis = "unknown"` until that is verified.

Docs: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from urllib.parse import quote

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

BASE_URL = "https://api.upstox.com/v3/historical-candle"
CHUNK_DAYS = 365  # ask for at most a year per request
_SEGMENT = {"NSE": "NSE_EQ", "BSE": "BSE_EQ"}


class UpstoxMarketDataAdapter(MarketDataProvider):
    source_code = "upstox"
    price_basis = "unknown"

    def __init__(
        self, client: httpx.Client | None = None, min_interval_seconds: float = 0.5, max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client or httpx.Client(timeout=20, headers={"Accept": "application/json"})
        self.policy = CallPolicy(self.source_code, min_interval_seconds, max_attempts, sleep)

    def instrument_key(self, listing: ListingKey) -> str:
        if self.source_code in listing.overrides:
            return listing.overrides[self.source_code]
        if listing.exchange not in _SEGMENT or not listing.isin:
            raise NotSupportedError("upstox needs an NSE/BSE listing with an ISIN")
        return f"{_SEGMENT[listing.exchange]}|{listing.isin}"

    def _fetch(self, key: str, start: date, end: date) -> list[list]:
        url = f"{BASE_URL}/{quote(key, safe='')}/days/1/{end.isoformat()}/{start.isoformat()}"
        response = self.client.get(url)
        if response.status_code in (400, 404):
            raise ProviderError(f"upstox rejected {key}: HTTP {response.status_code}")
        response.raise_for_status()  # 429 / 5xx -> retried by the policy
        payload = response.json()
        if payload.get("status") != "success":
            raise ProviderError(f"upstox error for {key}: {str(payload)[:200]}")
        return payload.get("data", {}).get("candles", []) or []

    def get_price_history(self, listing: ListingKey, start: date, end: date) -> PriceHistory:
        key = self.instrument_key(listing)
        bars = {}
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(end, chunk_start + timedelta(days=CHUNK_DAYS - 1))
            candles = self.policy.call(
                "historical-candle", key,
                lambda s=chunk_start, e=chunk_end: self._fetch(key, s, e),
            )
            # Each candle: [timestamp, open, high, low, close, volume, open_interest]
            for candle in candles:
                if len(candle) < 6:
                    continue
                day = datetime.fromisoformat(str(candle[0])).date()
                if start <= day <= end:
                    bar = make_bar(day, *candle[1:6])
                    if bar:
                        bars[day] = bar
            chunk_start = chunk_end + timedelta(days=1)
        return PriceHistory(self.source_code, self.price_basis, [bars[d] for d in sorted(bars)])
