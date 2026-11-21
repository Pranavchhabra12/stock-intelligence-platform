"""Yahoo Finance adapter, via the unofficial `yfinance` library. Primary source.

Yahoo's data is for personal and educational use, has no SLA and can change or
rate-limit without notice. So this adapter spaces out and retries requests,
validates every row and skips bad ones, and never invents a value.

`yfinance` swallows network errors by default and returns empty data, which
would hide an outage and stop the fallback chain from working. So prices are
requested with `raise_errors=True`, and a company with no financial statements
at all is reported as a failure rather than as "nothing to store".

Yahoo's prices are split-adjusted: earlier prices are rescaled after a split or
bonus, recorded as `price_basis = "split_adjusted"`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from backend.providers.market_data.base import (
    CompanyProfile,
    CorporateAction,
    FinancialPeriodData,
    ListingKey,
    MarketDataProvider,
    NotSupportedError,
    PeriodType,
    PriceHistory,
    ProviderUnavailableError,
)
from backend.providers.market_data.validation import finite, make_bar, money
from backend.providers.retry import CallPolicy

# Yahoo row labels for each stored metric, in order of preference.
INCOME_ROWS: dict[str, tuple[str, ...]] = {
    "total_revenue": ("Total Revenue", "Operating Revenue"),
    "net_profit": ("Net Income Common Stockholders", "Net Income",
                   "Net Income From Continuing Operation Net Minority Interest"),
    "eps": ("Basic EPS", "Diluted EPS"),
}
BALANCE_ROWS: dict[str, tuple[str, ...]] = {
    "shareholders_equity": ("Stockholders Equity", "Common Stock Equity"),
    "shares_outstanding": ("Ordinary Shares Number", "Share Issued"),
}
_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


def _to_date(value: Any) -> date:
    return value.date() if hasattr(value, "date") else value


class YahooMarketDataAdapter(MarketDataProvider):
    source_code = "yfinance"
    price_basis = "split_adjusted"

    def __init__(
        self, min_interval_seconds: float = 1.0, max_attempts: int = 3,
        ticker_factory: Callable[[str], Any] | None = None, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = CallPolicy(self.source_code, min_interval_seconds, max_attempts, sleep)
        self._ticker_factory = ticker_factory

    def symbol_for(self, listing: ListingKey) -> str:
        if self.source_code in listing.overrides:
            return listing.overrides[self.source_code]
        if listing.exchange not in _SUFFIX:
            raise NotSupportedError(f"yfinance: unsupported exchange {listing.exchange}")
        return listing.symbol + _SUFFIX[listing.exchange]

    def _ticker(self, symbol: str) -> Any:
        if self._ticker_factory is None:
            import yfinance  # lazy: heavy, and only needed when collecting

            self._ticker_factory = yfinance.Ticker
        return self._ticker_factory(symbol)

    # ---------- prices ----------

    def get_price_history(self, listing: ListingKey, start: date, end: date) -> PriceHistory:
        symbol = self.symbol_for(listing)
        ticker = self._ticker(symbol)

        def fetch() -> Any:
            try:
                return ticker.history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                                      interval="1d", auto_adjust=False, actions=False, raise_errors=True)
            except Exception as exc:
                # "No prices in this range" (weekend, holiday) is a real answer, not a failure.
                if type(exc).__name__ == "YFPricesMissingError":
                    return None
                raise

        frame = self.policy.call("history", symbol, fetch)
        bars = []
        if frame is not None and len(frame):
            for idx, row in frame.iterrows():
                day = _to_date(idx)
                if start <= day <= end:
                    bar = make_bar(day, row.get("Open"), row.get("High"), row.get("Low"), row.get("Close"),
                                   row.get("Volume"), row.get("Adj Close"))
                    if bar:
                        bars.append(bar)
        return PriceHistory(self.source_code, self.price_basis, bars)

    # ---------- corporate actions ----------

    def get_corporate_actions(self, listing: ListingKey) -> list[CorporateAction]:
        symbol = self.symbol_for(listing)
        ticker = self._ticker(symbol)
        dividends = self.policy.call("dividends", symbol, lambda: ticker.dividends)
        splits = self.policy.call("splits", symbol, lambda: ticker.splits)

        actions: list[CorporateAction] = []
        for idx, value in (dividends.items() if dividends is not None else []):
            amount = finite(value)
            if amount and amount > 0:
                actions.append(CorporateAction(_to_date(idx), "dividend", amount=money(amount)))
        # Yahoo reports bonus issues as splits, so they are stored as splits.
        for idx, value in (splits.items() if splits is not None else []):
            ratio = finite(value)
            if ratio and ratio > 0:
                actions.append(CorporateAction(_to_date(idx), "split", ratio=Decimal(str(round(ratio, 6)))))
        return actions

    # ---------- financials ----------

    def get_financials(self, listing: ListingKey) -> list[FinancialPeriodData]:
        symbol = self.symbol_for(listing)
        ticker = self._ticker(symbol)
        statements = {
            ("quarterly", "income"): self.policy.call("quarterly_income_stmt", symbol,
                                                      lambda: ticker.quarterly_income_stmt),
            ("annual", "income"): self.policy.call("income_stmt", symbol, lambda: ticker.income_stmt),
            ("quarterly", "balance"): self.policy.call("quarterly_balance_sheet", symbol,
                                                       lambda: ticker.quarterly_balance_sheet),
            ("annual", "balance"): self.policy.call("balance_sheet", symbol, lambda: ticker.balance_sheet),
        }

        if all(frame is None or len(frame) == 0 for frame in statements.values()):
            # A listed company always has statements; none at all means Yahoo failed.
            raise ProviderUnavailableError(f"yfinance returned no financial statements for {symbol}")

        periods: dict[tuple[PeriodType, date], dict[str, Decimal]] = {}
        for (period_type, kind), frame in statements.items():
            if frame is None or len(frame) == 0:
                continue
            rows = INCOME_ROWS if kind == "income" else BALANCE_ROWS
            for column in frame.columns:
                metrics = periods.setdefault((period_type, _to_date(column)), {})
                for code, labels in rows.items():
                    for label in labels:
                        if label in frame.index:
                            value = finite(frame.at[label, column])
                            if value is not None:
                                metrics[code] = money(value)
                                break

        return [
            FinancialPeriodData(period_type=pt, period_end=end, metrics=m)
            for (pt, end), m in sorted(periods.items())
            if m
        ]

    # ---------- profile ----------

    def get_profile(self, listing: ListingKey) -> CompanyProfile | None:
        symbol = self.symbol_for(listing)
        ticker = self._ticker(symbol)
        info = self.policy.call("info", symbol, lambda: ticker.info) or {}
        profile = CompanyProfile(
            sector=info.get("sector") or None,
            industry=info.get("industry") or None,
            website=info.get("website") or None,
            description=info.get("longBusinessSummary") or None,
        )
        return profile if any(vars(profile).values()) else None
