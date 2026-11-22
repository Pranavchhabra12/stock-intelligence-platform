"""Key metrics computed on read from stored prices, dividends and reported financials.

Nothing here is stored: market cap, P/E and the rest change with every price, so
they are always worked out from the latest stored values (see metric_definitions).
Every value says what it was based on ("last 4 quarters to Sep 2026", "FY2026"),
and a value that can't be worked out honestly is null with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

QUARTER_GAP = range(80, 101)     # days between consecutive quarter ends
YEAR_GAP = range(355, 376)       # days between the same quarter a year apart
STALE_QUARTER = timedelta(days=200)


@dataclass(frozen=True)
class Period:
    period_end: date
    fiscal_year: int
    fiscal_quarter: int | None
    metrics: dict[str, float | None]

    @property
    def label(self) -> str:
        return f"Q{self.fiscal_quarter} FY{self.fiscal_year}" if self.fiscal_quarter else f"FY{self.fiscal_year}"


@dataclass(frozen=True)
class Value:
    value: float | None
    basis: str | None = None
    note: str | None = None


def month(d: date) -> str:
    return d.strftime("%b %Y")


def _with(periods: list[Period], code: str) -> list[Period]:
    return sorted((p for p in periods if p.metrics.get(code) is not None), key=lambda p: p.period_end, reverse=True)


def trailing_twelve_months(code: str, quarters: list[Period], annuals: list[Period], today: date) -> Value:
    """Sum of the last four consecutive quarters if they're all there and recent;
    otherwise the latest full year."""
    q = _with(quarters, code)[:4]
    if len(q) == 4 and today - q[0].period_end <= STALE_QUARTER and all(
            (q[i].period_end - q[i + 1].period_end).days in QUARTER_GAP for i in range(3)):
        return Value(sum(p.metrics[code] for p in q), f"last 4 quarters to {month(q[0].period_end)}")
    a = _with(annuals, code)
    if a:
        return Value(a[0].metrics[code], a[0].label)
    return Value(None, note="not reported")


def latest(code: str, *groups: list[Period]) -> Value:
    found = _with([p for g in groups for p in g], code)
    if not found:
        return Value(None, note="not reported")
    return Value(found[0].metrics[code], f"as of {month(found[0].period_end)}")


def growth(code: str, quarters: list[Period], annuals: list[Period]) -> Value:
    """Latest quarter vs the same quarter a year earlier; otherwise latest year vs the one before."""
    q = _with(quarters, code)
    if q:
        earlier = next((p for p in q[1:] if (q[0].period_end - p.period_end).days in YEAR_GAP), None)
        if earlier:
            return _change(q[0].metrics[code], earlier.metrics[code], f"{q[0].label} vs {earlier.label}")
    a = _with(annuals, code)
    if len(a) >= 2 and a[0].fiscal_year - a[1].fiscal_year == 1:
        return _change(a[0].metrics[code], a[1].metrics[code], f"{a[0].label} vs {a[1].label}")
    return Value(None, note="not enough reported periods")


def _change(new: float, old: float, basis: str) -> Value:
    if old <= 0:
        return Value(None, basis, "not meaningful (earlier value zero or negative)")
    return Value((new - old) / old * 100, basis)


def compute(close: float | None, quarters: list[Period], annuals: list[Period], dividends_12m: float,
            today: date) -> dict[str, Value]:
    eps = trailing_twelve_months("eps", quarters, annuals, today)
    profit = trailing_twelve_months("net_profit", quarters, annuals, today)
    equity = latest("shareholders_equity", quarters, annuals)
    shares = latest("shares_outstanding", quarters, annuals)
    no_price = Value(None, note="no price yet")

    out: dict[str, Value] = {}
    if close is None:
        out["market_cap"] = out["pe_ratio"] = out["pb_ratio"] = out["dividend_yield"] = no_price
    else:
        out["market_cap"] = Value(close * shares.value, f"shares {shares.basis}") if shares.value \
            else Value(None, note="shares outstanding not reported")
        if eps.value is None:
            out["pe_ratio"] = Value(None, note="EPS not reported")
        elif eps.value <= 0:
            out["pe_ratio"] = Value(None, f"EPS {eps.basis}", "not meaningful (loss-making)")
        else:
            out["pe_ratio"] = Value(close / eps.value, f"EPS {eps.basis}")
        if equity.value and shares.value and equity.value > 0:
            out["pb_ratio"] = Value(close / (equity.value / shares.value), f"book value {equity.basis}")
        else:
            out["pb_ratio"] = Value(None, note="equity or shares not reported")
        out["dividend_yield"] = Value(dividends_12m / close * 100, "dividends with ex-date in the last 12 months")
    if profit.value is not None and equity.value and equity.value > 0:
        out["roe"] = Value(profit.value / equity.value * 100, f"profit {profit.basis}, equity {equity.basis}")
    else:
        out["roe"] = Value(None, note="profit or equity not reported")
    out["revenue_growth_yoy"] = growth("total_revenue", quarters, annuals)
    out["profit_growth_yoy"] = growth("net_profit", quarters, annuals)
    out["eps_ttm"] = eps
    out["net_profit_ttm"] = profit
    out["revenue_ttm"] = trailing_twelve_months("total_revenue", quarters, annuals, today)
    return out


EXTRA_LABELS: dict[str, dict[str, Any]] = {
    "eps_ttm": {"label": "EPS (12 months)", "unit": "INR_PER_SHARE"},
    "net_profit_ttm": {"label": "Net profit (12 months)", "unit": "INR"},
    "revenue_ttm": {"label": "Revenue (12 months)", "unit": "INR"},
}
