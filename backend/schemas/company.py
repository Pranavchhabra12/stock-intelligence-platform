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
    is_tracked: bool = Field(False, description="Collected daily, analysed by AI and included in Power BI")
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
    is_tracked: bool = False
    tracked_at: datetime | None = None
    untracked_at: datetime | None = Field(None, description="When it was last removed from Power BI")
    can_remove: bool = Field(False, description="In Power BI and added by a visitor; the starting companies stay")
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
    cap: int = Field(..., description="How many companies Power BI can follow in this demo")
    tone_days: int
    companies: list[CompanyOverview]


class UntrackResponse(BaseModel):
    company_id: UUID
    company_name: str
    is_tracked: bool
    removed: bool = Field(..., description="False when the company wasn't in Power BI")
    tracked_count: int
    cap: int


class TrackResponse(BaseModel):
    company_id: UUID
    company_name: str
    is_tracked: bool
    created: bool = Field(..., description="False when the company was already in Power BI")
    tracked_count: int
    cap: int
    job_id: UUID | None = Field(None, description="A first full refresh, started when the company was added")
