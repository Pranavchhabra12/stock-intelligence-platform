"""Request and response schemas for company endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Exchange = Literal["NSE", "BSE"]


class Listing(BaseModel):
    listing_id: UUID
    exchange: Exchange
    symbol: str
    exchange_code: str | None = Field(None, description="BSE scrip code, e.g. 500325")
    isin: str | None = None
    series: str | None = None
    currency: str
    is_active: bool


class CompanySearchResult(BaseModel):
    company_id: UUID
    company_name: str
    sector: str | None = None
    industry: str | None = None
    score: float = Field(..., ge=0, le=1, description="Match strength, 1.0 = exact identifier")
    listings: list[Listing]


class SearchResponse(BaseModel):
    query: str
    count: int
    results: list[CompanySearchResult]


class CompanyDetail(BaseModel):
    company_id: UUID
    company_name: str
    legal_name: str | None = None
    cin: str | None = None
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    website: str | None = None
    is_active: bool
    updated_at: datetime
    listings: list[Listing]
    aliases: list[str]


class ToneDay(BaseModel):
    date: date
    score: float = Field(..., ge=-1, le=1)
    article_count: int


class CompanyOverview(BaseModel):
    company_id: UUID
    company_name: str
    sector: str | None = None
    exchange: Exchange
    symbol: str
    trade_date: date | None = None
    close: float | None = None
    change_pct: float | None = None
    tone_30d: list[ToneDay] = Field(default_factory=list, description="Daily news tone, oldest first")


class OverviewResponse(BaseModel):
    count: int
    tone_days: int
    companies: list[CompanyOverview]
