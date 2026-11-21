"""Read-side rules for news and documents (what the API returns)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.core.errors import NotFoundError
from backend.database.repositories import CompanyRepository
from backend.schemas.content import CompanyDocument, NewsArticle, NewsResponse, ReportsResponse


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
                   ac.relevance_score, ac.mention_type, s.source_code, s.attribution_text
            from app.article_companies ac
            join app.news_articles a using (article_id)
            join app.data_sources s on s.source_id = a.source_id
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
