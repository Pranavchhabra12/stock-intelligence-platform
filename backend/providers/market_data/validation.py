"""Shared row validation, so every provider applies the same rules."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any

from backend.providers.market_data.base import PriceBar


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def money(value: float) -> Decimal:
    return Decimal(str(round(value, 4)))


def make_bar(
    day: date, open_: Any, high: Any, low: Any, close: Any, volume: Any, adj_close: Any = None
) -> PriceBar | None:
    """Return a validated bar, or None if the row is unusable (never a guessed value)."""
    o, h, lo, c, vol = (finite(x) for x in (open_, high, low, close, volume))
    if None in (o, h, lo, c, vol) or min(o, h, lo, c) <= 0 or vol < 0:
        return None
    o, h, lo, c = (round(x, 4) for x in (o, h, lo, c))
    if not (lo <= min(o, c) and max(o, c) <= h):
        return None
    adj = finite(adj_close)
    return PriceBar(
        trade_date=day, open=money(o), high=money(h), low=money(lo), close=money(c),
        volume=int(vol), adj_close=money(adj) if adj and adj > 0 else None,
    )
