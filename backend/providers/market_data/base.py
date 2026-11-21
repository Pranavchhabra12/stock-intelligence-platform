"""The market-data provider interface.

Every price or fundamentals source implements `MarketDataProvider`. The rest of
the application only sees these types, so adding or replacing a provider means
writing one new adapter class.

Adapters receive a `ListingKey` (exchange, symbol, ISIN, BSE code) and work out
their own instrument identifier from it, so no provider-specific symbols leak
into the rest of the code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

PriceBasis = Literal["raw", "split_adjusted", "unknown"]
PeriodType = Literal["quarterly", "annual"]
ActionType = Literal["dividend", "split", "bonus"]

# The five values stored as reported. Everything else is derived later.
REPORTED_METRICS = ("total_revenue", "net_profit", "eps", "shareholders_equity", "shares_outstanding")


class ProviderError(Exception):
    """Base class for provider failures."""


class ProviderUnavailableError(ProviderError):
    """The provider could not be reached or kept failing after retries."""


class NotSupportedError(ProviderError):
    """This provider cannot serve this listing or this kind of data."""


@dataclass(frozen=True)
class ListingKey:
    exchange: str                     # NSE or BSE
    symbol: str                       # NSE symbol or BSE scrip id
    isin: str | None = None
    exchange_code: str | None = None  # BSE scrip code
    #: explicit provider symbols from app.listing_provider_ids, by source_code
    overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adj_close: Decimal | None = None


@dataclass(frozen=True)
class PriceHistory:
    source_code: str
    price_basis: PriceBasis
    bars: list[PriceBar]


@dataclass(frozen=True)
class CorporateAction:
    ex_date: date
    action_type: ActionType
    ratio: Decimal | None = None    # splits and bonuses: new shares per old share
    amount: Decimal | None = None   # dividends: INR per share


@dataclass(frozen=True)
class FinancialPeriodData:
    period_type: PeriodType
    period_end: date
    metrics: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class CompanyProfile:
    sector: str | None = None
    industry: str | None = None
    website: str | None = None
    description: str | None = None


class MarketDataProvider(ABC):
    #: matches app.data_sources.source_code
    source_code: str
    #: how this provider's prices are adjusted
    price_basis: PriceBasis

    @abstractmethod
    def get_price_history(self, listing: ListingKey, start: date, end: date) -> PriceHistory:
        """Daily bars from `start` to `end` inclusive. Empty bars if none."""

    def get_corporate_actions(self, listing: ListingKey) -> list[CorporateAction]:
        raise NotSupportedError(f"{self.source_code} does not provide corporate actions")

    def get_financials(self, listing: ListingKey) -> list[FinancialPeriodData]:
        raise NotSupportedError(f"{self.source_code} does not provide financials")

    def get_profile(self, listing: ListingKey) -> CompanyProfile | None:
        raise NotSupportedError(f"{self.source_code} does not provide company profiles")
