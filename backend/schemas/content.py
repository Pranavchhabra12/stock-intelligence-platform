"""Response schemas for news and company documents."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

NEWS_NOTE = ("Headlines and short descriptions link to the original publisher. "
             "Educational use only; not investment advice.")


class NewsArticle(BaseModel):
    article_id: UUID
    headline: str
    url: str
    publisher: str | None = None
    published_at: datetime | None = None
    snippet: str | None = Field(None, description="The publisher's own short description, if any")
    relevance: float = Field(..., ge=0, le=1, description="1.0 = company named in the headline")
    mention_type: Literal["headline", "snippet", "query"]
    source: str = Field(..., description="Feed or search that found the article")
    source_attribution: str | None = None
    sentiment: Literal["positive", "neutral", "negative"] | None = Field(
        None, description="AI-rated tone for this company; null until analysed")
    sentiment_score: float | None = Field(None, ge=-1, le=1)


class NewsResponse(BaseModel):
    company_id: UUID
    company_name: str
    min_relevance: float
    count: int
    next_before: datetime | None = Field(None, description="Pass as `before` to get the next page")
    note: str = NEWS_NOTE
    articles: list[NewsArticle]


class CompanyDocument(BaseModel):
    document_id: UUID
    document_type: str
    title: str
    url: str
    publication_date: date | None = None
    fiscal_period: str | None = None
    source: str
    extraction_status: Literal["pending", "extracted", "needs_ocr", "not_pdf", "failed"]
    page_count: int | None = None
    chunk_count: int
    word_count: int


class ReportsResponse(BaseModel):
    company_id: UUID
    company_name: str
    count: int
    documents: list[CompanyDocument]


SENTIMENT_NOTE = ("AI-rated tone of recent news about the company. It describes the news, "
                  "not where the share price will go. Not investment advice.")
ANALYSIS_NOTE = ("AI-generated from the report text. Figures are copied from the report and every point "
                 "cites its pages; check the original report before relying on it. Not investment advice.")


class SentimentDay(BaseModel):
    date: date
    score: float = Field(..., ge=-1, le=1, description="Relevance-weighted mean, -1 to 1")
    article_count: int
    positive: int
    neutral: int
    negative: int


class SentimentResponse(BaseModel):
    company_id: UUID
    company_name: str
    methodology_version: str
    days: int
    overall_score: float | None = Field(None, description="Article-weighted mean over the period")
    overall_label: Literal["positive", "neutral", "negative"] | None = None
    article_count: int
    note: str = SENTIMENT_NOTE
    history: list[SentimentDay] = Field(..., description="Oldest first; days without news are left out")


class SummaryPoint(BaseModel):
    point: str
    pages: list[int]


class ReportSummary(BaseModel):
    document_id: UUID
    document_type: str
    title: str
    url: str
    fiscal_period: str | None = None
    summary: str
    key_points: list[SummaryPoint]
    risks: list[SummaryPoint]
    model: str
    prompt_version: str
    created_at: datetime


class AnalysisResponse(BaseModel):
    company_id: UUID
    company_name: str
    count: int
    note: str = ANALYSIS_NOTE
    reports: list[ReportSummary]
