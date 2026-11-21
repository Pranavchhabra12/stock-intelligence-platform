"""Try providers in order until one answers.

Prices: the first provider whose answer looks complete wins. "Complete" means
at least MIN_COVERAGE of the weekdays in the range (holidays make 100%
impossible). If a provider fails, returns nothing, or returns a thin answer
(e.g. one day out of five years), the next is asked; if nobody is complete,
the fullest answer is used. Every price row is stored with the source that
actually supplied it.

Corporate actions, financials and profile: the first provider that supports
them and succeeds wins (today only Yahoo supports them).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import date
from typing import TypeVar

from backend.providers.market_data.base import (
    CompanyProfile,
    CorporateAction,
    FinancialPeriodData,
    ListingKey,
    MarketDataProvider,
    NotSupportedError,
    PriceHistory,
    ProviderError,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")

# Indian exchanges close on ~15 weekday holidays a year (~6%); below 80% of
# weekdays means data is missing, not that the market was shut.
MIN_COVERAGE = 0.8
# Ranges this short (a daily update) are accepted with any rows at all.
MIN_WEEKDAYS_TO_CHECK = 5


def weekdays_between(start: date, end: date) -> int:
    if end < start:
        return 0
    days = (end - start).days + 1
    full_weeks, extra = divmod(days, 7)
    count = full_weeks * 5
    for i in range(extra):
        if (start.weekday() + i) % 7 < 5:
            count += 1
    return count


def is_complete(history: PriceHistory, start: date, end: date) -> bool:
    expected = weekdays_between(start, end)
    if expected < MIN_WEEKDAYS_TO_CHECK:
        return bool(history.bars)
    return len(history.bars) >= MIN_COVERAGE * expected


class FallbackMarketDataProvider(MarketDataProvider):
    source_code = "fallback"
    price_basis = "unknown"

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = list(providers)

    @property
    def source_codes(self) -> list[str]:
        return [p.source_code for p in self.providers]

    def get_price_history(self, listing: ListingKey, start: date, end: date) -> PriceHistory:
        errors: list[str] = []
        best: PriceHistory | None = None
        for i, provider in enumerate(self.providers):
            try:
                history = provider.get_price_history(listing, start, end)
            except ProviderError as exc:
                errors.append(f"{provider.source_code}: {exc}")
                logger.warning("price_provider_failed", extra={"provider": provider.source_code,
                                                              "symbol": listing.symbol, "error": str(exc)})
                continue
            if is_complete(history, start, end):
                if i > 0:
                    logger.info("price_fallback_used", extra={"provider": provider.source_code,
                                                              "symbol": listing.symbol})
                return history
            if history.bars:
                logger.warning("price_data_incomplete", extra={
                    "provider": provider.source_code, "symbol": listing.symbol, "exchange": listing.exchange,
                    "bars": len(history.bars), "weekdays": weekdays_between(start, end)})
            if best is None or len(history.bars) > len(best.bars):
                best = history
        if best is not None:
            return best  # nobody was complete: use the fullest answer (may be empty, e.g. a holiday)
        raise ProviderError("all price providers failed: " + "; ".join(errors))

    def first_available(self, what: str, fn: Callable[[MarketDataProvider], T]) -> tuple[str, T]:
        """(source_code, result) from the first provider that supports `what` and succeeds."""
        errors: list[str] = []
        for provider in self.providers:
            try:
                return provider.source_code, fn(provider)
            except NotSupportedError:
                continue
            except ProviderError as exc:
                errors.append(f"{provider.source_code}: {exc}")
        raise ProviderError(f"no provider could supply {what}: " + ("; ".join(errors) or "not supported"))

    def get_corporate_actions(self, listing: ListingKey) -> list[CorporateAction]:
        return self.first_available("corporate actions", lambda p: p.get_corporate_actions(listing))[1]

    def get_financials(self, listing: ListingKey) -> list[FinancialPeriodData]:
        return self.first_available("financials", lambda p: p.get_financials(listing))[1]

    def get_profile(self, listing: ListingKey) -> CompanyProfile | None:
        return self.first_available("profile", lambda p: p.get_profile(listing))[1]
