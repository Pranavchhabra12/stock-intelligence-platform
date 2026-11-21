"""Try providers in order until one answers.

Prices: the first provider that returns rows wins. If one fails or returns
nothing, the next is asked. Every price row is stored with the source that
actually supplied it, so mixed sources stay visible.

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
        empty: PriceHistory | None = None
        for provider in self.providers:
            try:
                history = provider.get_price_history(listing, start, end)
            except ProviderError as exc:
                errors.append(f"{provider.source_code}: {exc}")
                logger.warning("price_provider_failed", extra={"provider": provider.source_code,
                                                              "symbol": listing.symbol, "error": str(exc)})
                continue
            if history.bars:
                if errors:
                    logger.info("price_fallback_used", extra={"provider": provider.source_code,
                                                              "symbol": listing.symbol})
                return history
            empty = empty or history
        if empty is not None:
            return empty  # every provider answered but had no rows (e.g. a holiday)
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
