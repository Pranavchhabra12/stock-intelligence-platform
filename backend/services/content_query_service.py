"""Read-side rules for news and documents (what the API returns)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.core.errors import NotFoundError
from backend.database.repositories import CompanyRepository
from backend.schemas.content import (
    AnalysisResponse,
    CompanyDocument,
    NewsArticle,
    NewsResponse,
    ReportsResponse,
    ReportSummary,
    SentimentDay,
    SentimentResponse,
)
from backend.services.ai_analysis import METHODOLOGY_VERSION

LABEL_THRESHOLD = 0.15   # overall score above this is "positive", below minus this "negative"


class ContentQueryService:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.companies = CompanyRepository(conn)

    def _company(self, ticker: str) -> tuple:
        company_id = self.companies.find_company_id_by_ticker(ticker.strip(), None)
        if company_id is None:
            raise NotFoundError(f"No company found for ticker '{ticker}'.")
        return company_id, self.companies.get_company(company_id)["company_name"]

    def news(self, ticker: str, limit: int, min_relevance: float, before: datetime | None) -> NewsResponse:
        company_id, name = self._company(ticker)
        rows = self.conn.execute(text(
            """
            select a.article_id, a.headline, a.canonical_url as url, a.publisher, a.snippet,
                   coalesce(a.published_at, a.collected_at) as sort_time, a.published_at,
                   ac.relevance_score, ac.mention_type, s.source_code, s.attribution_text,
                   ai.sentiment_label, ai.sentiment_score
            from app.article_companies ac
            join app.news_articles a using (article_id)
            join app.data_sources s on s.source_id = a.source_id
            left join lateral (
              select x.sentiment_label, x.sentiment_score from app.ai_analyses x
              where x.company_id = ac.company_id and x.article_id = ac.article_id and x.status = 'completed'
              order by x.created_at desc limit 1
            ) ai on true
            where ac.company_id = :cid
              and ac.relevance_score >= :minrel
              and (cast(:before as timestamptz) is null or coalesce(a.published_at, a.collected_at) < :before)
            order by sort_time desc, a.article_id
            limit :limit
            """
        ), {"cid": company_id, "minrel": min_relevance, "before": before, "limit": limit}).mappings().all()
        articles = [
            NewsArticle(
                article_id=r["article_id"], headline=r["headline"], url=r["url"], publisher=r["publisher"],
                published_at=r["published_at"], snippet=r["snippet"], relevance=float(r["relevance_score"]),
                mention_type=r["mention_type"], source=r["source_code"], source_attribution=r["attribution_text"],
                sentiment=r["sentiment_label"],
                sentiment_score=float(r["sentiment_score"]) if r["sentiment_score"] is not None else None,
            )
            for r in rows
        ]
        return NewsResponse(
            company_id=company_id, company_name=name, min_relevance=min_relevance, count=len(articles),
            next_before=rows[-1]["sort_time"] if len(rows) == limit else None, articles=articles,
        )

    def reports(self, ticker: str, document_type: str | None) -> ReportsResponse:
        company_id, name = self._company(ticker)
        rows = self.conn.execute(text(
            """
            select d.document_id, d.document_type, d.document_title, d.document_url, d.publication_date,
                   d.fiscal_period, s.source_code, d.extraction_status, d.page_count,
                   count(c.chunk_id) as chunk_count, coalesce(sum(c.word_count), 0) as word_count
            from app.company_documents d
            join app.data_sources s on s.source_id = d.source_id
            left join app.document_chunks c using (document_id)
            where d.company_id = :cid and (cast(:dtype as text) is null or d.document_type = :dtype)
            group by d.document_id, s.source_code
            order by d.publication_date desc nulls last, d.collected_at desc
            """
        ), {"cid": company_id, "dtype": document_type}).mappings().all()
        documents = [
            CompanyDocument(
                document_id=r["document_id"], document_type=r["document_type"], title=r["document_title"],
                url=r["document_url"], publication_date=r["publication_date"], fiscal_period=r["fiscal_period"],
                source=r["source_code"], extraction_status=r["extraction_status"], page_count=r["page_count"],
                chunk_count=r["chunk_count"], word_count=r["word_count"],
            )
            for r in rows
        ]
        return ReportsResponse(company_id=company_id, company_name=name, count=len(documents), documents=documents)

    def sentiment(self, ticker: str, days: int) -> SentimentResponse:
        company_id, name = self._company(ticker)
        rows = self.conn.execute(text(
            """
            select as_of_date, sentiment_score, article_count, positive_count, neutral_count, negative_count
            from app.sentiment_history
            where company_id = :cid and methodology_version = :mv
              and as_of_date >= (now() at time zone 'Asia/Kolkata')::date - :days
            order by as_of_date
            """
        ), {"cid": company_id, "mv": METHODOLOGY_VERSION, "days": days}).mappings().all()
        history = [
            SentimentDay(date=r["as_of_date"], score=float(r["sentiment_score"]), article_count=r["article_count"],
                         positive=r["positive_count"], neutral=r["neutral_count"], negative=r["negative_count"])
            for r in rows
        ]
        total = sum(d.article_count for d in history)
        overall = round(sum(d.score * d.article_count for d in history) / total, 3) if total else None
        label = None if overall is None else (
            "positive" if overall > LABEL_THRESHOLD else "negative" if overall < -LABEL_THRESHOLD else "neutral")
        return SentimentResponse(
            company_id=company_id, company_name=name, methodology_version=METHODOLOGY_VERSION, days=days,
            overall_score=overall, overall_label=label, article_count=total, history=history,
        )

    def analysis(self, ticker: str) -> AnalysisResponse:
        company_id, name = self._company(ticker)
        rows = self.conn.execute(text(
            """
            select distinct on (d.document_id)
                   d.document_id, d.document_type, d.document_title, d.document_url, d.fiscal_period,
                   d.publication_date, x.summary, x.key_points, x.risks, x.model, x.prompt_version, x.created_at
            from app.ai_analyses x join app.company_documents d using (document_id)
            where x.company_id = :cid and x.analysis_type = 'document_summary' and x.status = 'completed'
            order by d.document_id, x.created_at desc
            """
        ), {"cid": company_id}).mappings().all()
        rows = sorted(rows, key=lambda r: (r["publication_date"] is not None, r["publication_date"]), reverse=True)
        reports = [
            ReportSummary(
                document_id=r["document_id"], document_type=r["document_type"], title=r["document_title"],
                url=r["document_url"], fiscal_period=r["fiscal_period"], summary=r["summary"],
                key_points=r["key_points"], risks=r["risks"], model=r["model"],
                prompt_version=r["prompt_version"], created_at=r["created_at"],
            )
            for r in rows
        ]
        return AnalysisResponse(company_id=company_id, company_name=name, count=len(reports), reports=reports)
