"""IndianAPI.in company results: quarterly and annual income statement and balance sheet.

Used for results only (not prices). It fills the gaps Yahoo leaves for Indian companies:
recent quarters Yahoo hasn't published, and its padded, mostly empty older columns.

One request per company returns every period (about 7 years and 11 quarters), so results are
fetched only when due, keeping well inside the free plan's 500 requests a month. See
`MarketDataCollector` for the schedule.

Figures arrive in ₹ crore (shares in crore too); they are stored in rupees and shares, like
Yahoo's. Quarterly rows are single quarters (periodLength 3), not year-to-date totals.

Docs: https://indianapi.in (Indian Stock API, `GET /stock?name=…`, header `x-api-key`)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from backend.providers.market_data.base import (
    FinancialPeriodData,
    ListingKey,
    MarketDataProvider,
    NotSupportedError,
    PriceHistory,
    ProviderError,
)
from backend.providers.market_data.validation import finite
from backend.providers.retry import CallPolicy

BASE_URL = "https://stock.indianapi.in"
CRORE = Decimal(10_000_000)
FOUR_PLACES = Decimal("0.0001")   # financial_metrics.value is numeric(24, 4)


def _number(section: dict[str, Any], *keys: str) -> Decimal | None:
    """The first of `keys` holding a real number, kept exact as a Decimal."""
    for key in keys:
        if finite(section.get(key)) is not None:
            return Decimal(str(section[key]).strip())
    return None


def parse_period(item: dict[str, Any]) -> FinancialPeriodData | None:
    """One period of IndianAPI's `financials` list, or None if it isn't a full year or a single quarter."""
    kind = item.get("Type")
    try:
        end = date.fromisoformat(str(item.get("EndDate")))
    except ValueError:
        return None
    statements = item.get("stockFinancialMap") or {}
    inc = {row.get("key"): row.get("value") for row in statements.get("INC") or [] if isinstance(row, dict)}
    bal = {row.get("key"): row.get("value") for row in statements.get("BAL") or [] if isinstance(row, dict)}
    length = str(inc.get("periodLength") or "")
    if kind == "Annual" and length in ("12", ""):
        period_type = "annual"
    elif kind == "Interim" and length == "3":
        period_type = "quarterly"
    else:
        return None     # half-year or year-to-date figures: not comparable with the rest

    metrics: dict[str, Decimal] = {}
    revenue = _number(inc, "TotalRevenue", "Revenue")
    if revenue is None:
        # Banks report no "revenue": their total income is interest earned plus other income.
        interest, other = _number(inc, "InterestIncomeBank"), _number(inc, "Non-InterestIncomeBank")
        if interest is not None and other is not None:
            revenue = interest + other
    crore_values = {
        "total_revenue": revenue,
        "net_profit": _number(inc, "NetIncome", "IncomeAvailabletoComInclExtraOrd"),
        "shareholders_equity": _number(bal, "TotalEquity"),
        "shares_outstanding": _number(bal, "TotalCommonSharesOutstanding"),
    }
    for code, value in crore_values.items():
        if value is not None:
            metrics[code] = (value * CRORE).quantize(FOUR_PLACES)
    eps = _number(inc, "DilutedEPSExcludingExtraOrdItems", "DilutedNormalizedEPS")
    if eps is not None:
        metrics["eps"] = eps.quantize(FOUR_PLACES)
    return FinancialPeriodData(period_type=period_type, period_end=end, metrics=metrics) if metrics else None


class IndianApiResultsAdapter(MarketDataProvider):
    source_code = "indianapi"
    price_basis = "unknown"

    def __init__(
        self, api_key: str, client: httpx.Client | None = None, max_attempts: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=30)
        self.policy = CallPolicy(self.source_code, 1.0, max_attempts, sleep)

    def get_price_history(self, listing: ListingKey, start: date, end: date) -> PriceHistory:
        raise NotSupportedError("indianapi is used for results only")

    def _fetch(self, symbol: str) -> dict[str, Any]:
        response = self.client.get(f"{BASE_URL}/stock", params={"name": symbol},
                                   headers={"x-api-key": self.api_key})
        if response.status_code in (401, 403):
            raise ProviderError(f"indianapi refused the key: HTTP {response.status_code}")
        if response.status_code == 429:
            raise ProviderError("indianapi request limit reached for now")
        if response.status_code == 404:
            raise ProviderError(f"indianapi has no company {symbol}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("financials"), list):
            raise ProviderError(f"indianapi unexpected response for {symbol}")
        return data

    def get_financials(self, listing: ListingKey) -> list[FinancialPeriodData]:
        if listing.exchange != "NSE":
            raise NotSupportedError("indianapi is looked up by NSE symbol")
        symbol = listing.overrides.get(self.source_code, listing.symbol)
        data = self.policy.call("stock", symbol, lambda: self._fetch(symbol))
        # The lookup is by name, so make sure it found the same company.
        isin = (data.get("companyProfile") or {}).get("isInId")
        if listing.isin and isin and isin != listing.isin:
            raise ProviderError(f"indianapi matched {symbol} to a different company ({isin})")
        periods = [p for p in (parse_period(item) for item in data["financials"] if isinstance(item, dict)) if p]
        if not periods:
            raise ProviderError(f"indianapi has no results for {symbol}")
        # One row per period; if a period repeats, keep the fuller one.
        best: dict[tuple[str, date], FinancialPeriodData] = {}
        for p in periods:
            key = (p.period_type, p.period_end)
            if key not in best or len(p.metrics) > len(best[key].metrics):
                best[key] = p
        return [best[k] for k in sorted(best)]
