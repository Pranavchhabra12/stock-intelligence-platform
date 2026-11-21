"""In-memory providers for tests: deterministic, no network."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from backend.providers.market_data.base import (
    CompanyProfile,
    CorporateAction,
    FinancialPeriodData,
    ListingKey,
    MarketDataProvider,
    PriceBar,
    PriceHistory,
    ProviderUnavailableError,
)


def weekday_bars(start: date, end: date, base: float = 100.0) -> list[PriceBar]:
    bars, day, i = [], start, 0
    while day <= end:
        if day.weekday() < 5:
            p = Decimal(str(base + i))
            bars.append(PriceBar(day, p, p + 2, p - 1, p + 1, 1000 + i))
            i += 1
        day += timedelta(days=1)
    return bars


class FakeProvider(MarketDataProvider):
    def __init__(
        self, source_code: str = "yfinance", price_basis: str = "split_adjusted", *,
        fail_prices: bool = False, empty_prices: bool = False,
        actions: list[CorporateAction] | None = None,
        financials: list[FinancialPeriodData] | None = None,
        profile: CompanyProfile | None = None,
        supports_fundamentals: bool = True,
    ) -> None:
        self.source_code = source_code
        self.price_basis = price_basis  # type: ignore[assignment]
        self.fail_prices = fail_prices
        self.empty_prices = empty_prices
        self.actions = actions or []
        self.financials = financials or []
        self.profile = profile
        self.supports_fundamentals = supports_fundamentals
        self.price_calls: list[tuple[str, date, date]] = []

    def get_price_history(self, listing: ListingKey, start: date, end: date) -> PriceHistory:
        self.price_calls.append((listing.exchange, start, end))
        if self.fail_prices:
            raise ProviderUnavailableError(f"{self.source_code} is down")
        bars = [] if self.empty_prices else weekday_bars(start, end)
        return PriceHistory(self.source_code, self.price_basis, bars)  # type: ignore[arg-type]

    def get_corporate_actions(self, listing: ListingKey) -> list[CorporateAction]:
        if not self.supports_fundamentals:
            return super().get_corporate_actions(listing)
        return self.actions

    def get_financials(self, listing: ListingKey) -> list[FinancialPeriodData]:
        if not self.supports_fundamentals:
            return super().get_financials(listing)
        return self.financials

    def get_profile(self, listing: ListingKey) -> CompanyProfile | None:
        if not self.supports_fundamentals:
            return super().get_profile(listing)
        return self.profile
