"""Collect news and exchange filings, link them to companies, and store them once.

Sources:
- publisher RSS feeds and BSE's official filing feeds (market-wide): every item
  is matched against our companies; items about none of them are dropped;
- Google News search (per company): headlines naming the company, from the
  last few days (a month on the first run).
- GDELT (best effort): one combined search for a batch of companies. GDELT
  often refuses requests from cloud servers, so failures are only warnings.
Search engines match the whole article, so for both searches only results
whose headline names the company are kept.

Deduplication:
- the same URL (after canonicalisation) is stored once;
- the same headline within two days under another URL (syndication) is
  treated as the same story: the existing article gains the new company links.

Filing items from BSE's results and annual-report feeds also register a
company document (fetched and parsed later by the document service).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, text

from backend.providers.market_data.base import ProviderError
from backend.providers.news.base import NewsItem, canonical_url, headline_hash, url_hash
from backend.providers.news.gdelt import GdeltNewsAdapter
from backend.providers.news.rss import DEFAULT_FEEDS, Feed, RssAdapter, google_news_feed
from backend.services.company_matcher import CompanyMatcher, Match

logger = logging.getLogger(__name__)

SYNDICATION_WINDOW = timedelta(days=2)
# Search results that aren't news: live-quote pages, stock profile pages and social posts.
NOT_NEWS_TITLE = re.compile(
    r"share price (today|live)|stock price (today|live)|live (nse|bse)|stock price & chart"
    r"|stock price, news, quote|price, news, quote|\(\w+:\w+\) - stock analysis|share price prediction",
    re.I,
)
NOT_NEWS_PUBLISHERS = {"facebook", "instagram", "x", "twitter", "youtube", "linkedin", "reddit", "threads"}


def is_not_news(item: NewsItem) -> bool:
    return bool(NOT_NEWS_TITLE.search(item.headline)) or (item.publisher or "").strip().lower() in NOT_NEWS_PUBLISHERS
DOCUMENT_FEEDS = {"bse_financial_results": "quarterly_results", "bse_annual_reports": "annual_report"}
# Announcement subjects that are worth keeping as documents, checked in order.
ANNOUNCEMENT_DOCUMENTS = (
    ("financial result", "quarterly_results"),
    ("annual report", "annual_report"),
    ("investor presentation", "investor_presentation"),
    ("transcript", "earnings_transcript"),
)


def document_type_for(item: NewsItem) -> str | None:
    if item.source_code in DOCUMENT_FEEDS:
        return DOCUMENT_FEEDS[item.source_code]
    if item.kind == "exchange_filing" and ".pdf" in item.url.lower():
        subject = item.headline.lower()
        for keyword, doc_type in ANNOUNCEMENT_DOCUMENTS:
            if keyword in subject:
                return doc_type
    return None


GDELT_BATCH_SIZE = 8   # keeps the OR query well under GDELT's length limit


def _batches(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


@dataclass
class NewsResult:
    items_seen: int = 0
    articles_new: int = 0
    duplicates: int = 0
    links_new: int = 0
    unmatched_dropped: int = 0
    documents_registered: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.errors:
            return "completed"
        return "completed_with_errors" if self.items_seen else "failed"


class NewsCollector:
    def __init__(
        self, engine: Engine, gdelt: GdeltNewsAdapter | None = None, rss: RssAdapter | None = None,
        feeds: tuple[Feed, ...] = DEFAULT_FEEDS, now: datetime | None = None, search: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.engine = engine
        self.gdelt = gdelt
        self.rss = rss
        self.feeds = feeds
        self.search = search
        self.sleep = sleep
        self.now = now or datetime.now(UTC)

    # ---------- entry points ----------

    def collect(self, company_ids: list[UUID] | None = None) -> NewsResult:
        result = NewsResult()
        with self.engine.connect() as conn:
            self.source_ids = dict(conn.execute(text("select source_code, source_id from app.data_sources")).all())
            matcher = CompanyMatcher.from_database(conn, company_ids)
            companies = conn.execute(text(
                """
                select c.company_id, c.company_name,
                       array_agg(a.alias) filter (where a.alias_type in ('name', 'legal_name')
                                                  and a.alias like '% %') as names,
                       exists (select 1 from app.article_companies ac where ac.company_id = c.company_id) as has_news
                from app.companies c left join app.company_aliases a using (company_id)
                where (cast(:ids as uuid[]) is null and c.is_tracked) or c.company_id = any(:ids)
                group by c.company_id
                """
            ), {"ids": company_ids}).mappings().all()
        wanted = {c["company_id"] for c in companies}

        if self.rss:
            for feed in self.feeds:
                try:
                    items = self.rss.fetch(feed)
                except ProviderError as exc:
                    result.errors.append(f"{feed.source_code}: {exc}")
                    continue
                for item in items:
                    result.items_seen += 1
                    matches = [m for m in matcher.match(item.headline, item.snippet, item.exchange_code)
                               if m.company_id in wanted]
                    if not matches:
                        result.unmatched_dropped += 1
                        continue
                    self._store(item, matches, result)
                    doc_type = document_type_for(item)
                    if doc_type:
                        self._register_document(item, matches, doc_type, result)

        if self.rss and self.search:
            for i, c in enumerate(companies):
                if i:
                    self.sleep(1.0)   # be gentle: one search a second
                names = sorted({c["company_name"], *(c["names"] or [])})
                feed = google_news_feed(names, days=3 if c["has_news"] else 30)
                try:
                    items = self.rss.fetch(feed)
                except ProviderError as exc:
                    result.errors.append(f"google news {c['company_name']}: {exc}")
                    continue
                self._store_headline_matches(items, matcher, wanted, result)

        if self.gdelt:
            # One combined search per batch of companies rather than one per company:
            # GDELT throttles hard, and the headline matcher works out which company
            # each result is about anyway.
            for batch in _batches(companies, GDELT_BATCH_SIZE):
                names = sorted({n for c in batch for n in (c["company_name"], *(c["names"] or []))})
                # First run looks back a month; afterwards a few days is enough.
                timespan = "3d" if all(c["has_news"] for c in batch) else "1m"
                label = ", ".join(c["company_name"] for c in batch)
                try:
                    items = self.gdelt.search(names, timespan=timespan, max_records=250)
                except (ProviderError, ValueError) as exc:
                    result.errors.append(f"gdelt ({label}): {exc}")
                    continue
                self._store_headline_matches(items, matcher, wanted, result)

        logger.info("news_collection_finished", extra={k: v for k, v in vars(result).items()})
        return result

    def _store_headline_matches(self, items: list[NewsItem], matcher: CompanyMatcher, wanted: set,
                                result: NewsResult) -> None:
        """Search results: keep only those whose headline names a company. Search engines match the
        whole article, so a result that only mentions the company in its body is too weak to keep."""
        for item in items:
            result.items_seen += 1
            matches = [] if is_not_news(item) else [m for m in matcher.match(item.headline) if m.company_id in wanted]
            if not matches:
                result.unmatched_dropped += 1
                continue
            self._store(item, matches, result)

    # ---------- storage ----------

    def _store(self, item: NewsItem, matches: list[Match], result: NewsResult) -> None:
        source_id = self.source_ids.get(item.source_code)
        if source_id is None:
            result.errors.append(f"data source '{item.source_code}' is not registered")
            return
        h_url, h_head = url_hash(item.url), headline_hash(item.headline)
        published = item.published_at or self.now
        with self.engine.begin() as conn:
            article_id = conn.execute(text("select article_id from app.news_articles where url_hash = :h"),
                                      {"h": h_url}).scalar()
            if article_id is None:
                article_id = conn.execute(text(
                    """
                    select article_id from app.news_articles
                    where content_hash = :h
                      and coalesce(published_at, collected_at) between :lo and :hi
                    limit 1
                    """
                ), {"h": h_head, "lo": published - SYNDICATION_WINDOW, "hi": published + SYNDICATION_WINDOW}).scalar()
            if article_id is not None:
                result.duplicates += 1
            else:
                article_id = conn.execute(text(
                    """
                    insert into app.news_articles
                      (source_id, canonical_url, url_hash, headline, snippet, publisher, published_at,
                       language, content_hash)
                    values (:sid, :url, :uh, :headline, :snippet, :publisher, :published, :language, :ch)
                    returning article_id
                    """
                ), {"sid": source_id, "url": canonical_url(item.url), "uh": h_url, "headline": item.headline[:1000],
                    "snippet": item.snippet, "publisher": item.publisher, "published": item.published_at,
                    "language": item.language, "ch": h_head}).scalar_one()
                result.articles_new += 1

            for m in matches:
                inserted = conn.execute(text(
                    """
                    insert into app.article_companies (article_id, company_id, relevance_score, mention_type)
                    values (:a, :c, :score, :mention)
                    on conflict (article_id, company_id) do update
                      set relevance_score = greatest(app.article_companies.relevance_score, excluded.relevance_score),
                          mention_type = case when excluded.relevance_score > app.article_companies.relevance_score
                                              then excluded.mention_type else app.article_companies.mention_type end
                    returning (xmax = 0)
                    """
                ), {"a": article_id, "c": m.company_id, "score": m.score, "mention": m.mention_type}).scalar_one()
                result.links_new += int(bool(inserted))

    def _register_document(self, item: NewsItem, matches: list[Match], doc_type: str, result: NewsResult) -> None:
        # Only the strongest match owns a filing: a filing belongs to one company.
        best = max(matches, key=lambda m: m.score)
        if best.score < 0.85:
            return
        with self.engine.begin() as conn:
            inserted = conn.execute(text(
                """
                insert into app.company_documents
                  (company_id, source_id, document_type, document_title, document_url, publication_date)
                values (:c, :s, :t, :title, :url, :pub)
                on conflict (company_id, document_url) do nothing
                returning document_id
                """
            ), {"c": best.company_id, "s": self.source_ids[item.source_code], "t": doc_type,
                "title": item.headline[:500], "url": item.url,
                "pub": item.published_at.date() if item.published_at else None}).scalar()
        result.documents_registered += int(inserted is not None)
