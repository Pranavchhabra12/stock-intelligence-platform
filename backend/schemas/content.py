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
