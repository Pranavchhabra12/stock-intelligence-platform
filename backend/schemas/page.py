"""Everything a company page shows, in one response (one request instead of eleven)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas.company import CompanyDetail
from backend.schemas.content import AnalysisResponse, NewsResponse, ReportsResponse, SentimentResponse
from backend.schemas.jobs import Job
from backend.schemas.market import FinancialsResponse, PriceHistoryResponse, SummaryResponse


class Tracking(BaseModel):
    tracked_count: int
    cap: int


class CompanyPage(BaseModel):
    company: CompanyDetail
    summary: SummaryResponse | None = None
    prices: PriceHistoryResponse | None = Field(None, description="The last year of daily prices")
    quarterly: FinancialsResponse | None = None
    annual: FinancialsResponse | None = None
    news: NewsResponse | None = None
    sentiment: SentimentResponse | None = None
    analysis: AnalysisResponse | None = None
    reports: ReportsResponse | None = None
    last_job: Job | None = None
    tracking: Tracking
    missing: list[str] = Field(default_factory=list, description="Sections that failed to load")
