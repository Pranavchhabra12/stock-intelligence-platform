"""Response schemas for prices and financials."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from backend.schemas.company import Exchange

DATA_NOTE = "End-of-day data, delayed. Educational use only; not investment advice."


class SourceInfo(BaseModel):
    code: str
    name: str
    attribution: str | None = None


class PriceRow(BaseModel):
    trade_date: date
    source: str = Field(..., description="Provider that supplied this row")
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None = None
    volume: int


class ListingRef(BaseModel):
    listing_id: UUID
    exchange: Exchange
    symbol: str
    exchange_code: str | None = None


class PriceHistoryResponse(BaseModel):
    company_id: UUID
    company_name: str
    listing: ListingRef
    start: date
    end: date
    price_basis: Literal["raw", "split_adjusted", "unknown", "mixed"] | None = Field(
        None, description="split_adjusted: earlier prices rescaled after splits and bonuses; "
                          "mixed: rows came from providers with different bases"
    )
    sources: list[SourceInfo] = Field(default_factory=list, description="Every provider behind these rows")
    data_note: str = DATA_NOTE
    count: int
    prices: list[PriceRow]


class FinancialPeriod(BaseModel):
    label: str = Field(..., description="e.g. Q2 FY2026 or FY2025")
    period_type: Literal["quarterly", "annual"]
    period_end: date
    fiscal_year: int
    fiscal_quarter: int | None = None
    consolidation: Literal["consolidated", "standalone", "unknown"]
    metrics: dict[str, float | None]


class MetricInfo(BaseModel):
    label: str
    unit: str


class FinancialsResponse(BaseModel):
    company_id: UUID
    company_name: str
    period_type: Literal["quarterly", "annual"]
    source: SourceInfo | None = None
    data_note: str = DATA_NOTE
    metric_definitions: dict[str, MetricInfo]
    periods: list[FinancialPeriod]


class PriceSnapshot(BaseModel):
    trade_date: date
    close: float
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    high_52w: float | None = Field(None, description="Highest high over the last 12 months")
    low_52w: float | None = Field(None, description="Lowest low over the last 12 months")
    source: str


class KeyMetric(BaseModel):
    code: str
    label: str
    unit: str = Field(..., description="INR, INR_PER_SHARE, RATIO or PERCENT")
    value: float | None = None
    basis: str | None = Field(None, description='What it was worked out from, e.g. "last 4 quarters to Sep 2026"')
    note: str | None = Field(None, description="Why the value is missing, if it is")


class SummaryResponse(BaseModel):
    company_id: UUID
    company_name: str
    sector: str | None = None
    industry: str | None = None
    listing: ListingRef
    price: PriceSnapshot | None = None
    metrics: list[KeyMetric]
    sources: list[SourceInfo] = Field(default_factory=list)
    data_note: str = DATA_NOTE
