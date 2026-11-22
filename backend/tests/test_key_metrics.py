"""Key metrics worked out on read: market cap, P/E, P/B, dividend yield, ROE, growth."""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.key_metrics import Period, compute, growth, trailing_twelve_months

TODAY = date(2026, 11, 21)


def q(end: date, fy: int, fq: int, **m: float) -> Period:
    return Period(end, fy, fq, m)


QUARTERS = [
    q(date(2026, 9, 30), 2027, 2, eps=20, net_profit=200, total_revenue=1100, shareholders_equity=4000,
      shares_outstanding=10),
    q(date(2026, 6, 30), 2027, 1, eps=18, net_profit=180, total_revenue=1000),
    q(date(2026, 3, 31), 2026, 4, eps=17, net_profit=170, total_revenue=950),
    q(date(2025, 12, 31), 2026, 3, eps=15, net_profit=150, total_revenue=900),
    q(date(2025, 9, 30), 2026, 2, eps=14, net_profit=140, total_revenue=1000),
]
ANNUALS = [Period(date(2026, 3, 31), 2026, None, {"eps": 60, "net_profit": 600, "total_revenue": 3800}),
           Period(date(2025, 3, 31), 2025, None, {"eps": 50, "net_profit": 500, "total_revenue": 3500})]


def test_ttm_uses_four_consecutive_quarters() -> None:
    v = trailing_twelve_months("eps", QUARTERS, ANNUALS, TODAY)
    assert v.value == 70 and v.basis == "last 4 quarters to Sep 2026"


def test_ttm_falls_back_to_the_latest_year_when_a_quarter_is_missing() -> None:
    gappy = [p for p in QUARTERS if p.fiscal_quarter != 4 or p.fiscal_year != 2026]
    v = trailing_twelve_months("eps", gappy, ANNUALS, TODAY)
    assert v.value == 60 and v.basis == "FY2026"
    stale = trailing_twelve_months("eps", QUARTERS, ANNUALS, date(2027, 6, 1))   # latest quarter too old
    assert stale.basis == "FY2026"
    assert trailing_twelve_months("eps", [], [], TODAY).note == "not reported"


def test_growth_compares_the_same_quarter_a_year_earlier() -> None:
    v = growth("total_revenue", QUARTERS, ANNUALS)
    assert v.value == pytest.approx(10.0) and v.basis == "Q2 FY2027 vs Q2 FY2026"
    annual_only = growth("total_revenue", [], ANNUALS)
    assert annual_only.value == pytest.approx(3800 / 3500 * 100 - 100) and annual_only.basis == "FY2026 vs FY2025"
    assert growth("total_revenue", [], ANNUALS[:1]).value is None


def test_all_metrics() -> None:
    m = compute(1400.0, QUARTERS, ANNUALS, dividends_12m=28.0, today=TODAY)
    assert m["market_cap"].value == 14000 and m["market_cap"].basis == "shares as of Sep 2026"
    assert m["pe_ratio"].value == pytest.approx(20.0)                       # 1400 / 70
    assert m["pb_ratio"].value == pytest.approx(3.5)                        # 1400 / (4000 / 10)
    assert m["dividend_yield"].value == pytest.approx(2.0)
    assert m["roe"].value == pytest.approx(700 / 4000 * 100)
    assert m["profit_growth_yoy"].value == pytest.approx((200 - 140) / 140 * 100)


def test_missing_and_meaningless_values_say_why() -> None:
    losses = [Period(date(2026, 3, 31), 2026, None, {"eps": -5.0})]
    m = compute(100.0, [], losses, dividends_12m=0, today=TODAY)
    assert m["pe_ratio"].value is None and "loss-making" in m["pe_ratio"].note
    assert m["market_cap"].value is None and m["market_cap"].note == "shares outstanding not reported"
    assert m["dividend_yield"].value == 0
    no_price = compute(None, QUARTERS, ANNUALS, 0, TODAY)
    assert no_price["pe_ratio"].note == "no price yet" and no_price["roe"].value is not None
