"""Stock and company endpoints: search, details, prices, financials, news, reports and AI analysis."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Response
from sqlalchemy.engine import Connection

from backend.api.jobs import JobServiceDep
from backend.core.config import get_settings
from backend.core.errors import NotFoundError
from backend.database.connection import get_connection, get_engine
from backend.database.repositories import CompanyRepository
from backend.schemas.company import (
    CompanyDetail,
    Exchange,
    OverviewResponse,
    SearchResponse,
    TrackResponse,
    UntrackResponse,
)
from backend.schemas.content import AnalysisResponse, NewsResponse, ReportsResponse, SentimentResponse
from backend.schemas.errors import ErrorResponse
from backend.schemas.jobs import Job, JobListResponse, RefreshResponse
from backend.schemas.market import FinancialsResponse, PriceHistoryResponse, SummaryResponse
from backend.schemas.page import CompanyPage, Tracking
from backend.services.company_service import CompanyService
from backend.services.content_query_service import ContentQueryService
from backend.services.market_query_service import MarketQueryService
from backend.services.overview_service import OverviewService
from backend.services.tracking_service import TrackingService

router = APIRouter(prefix="/stocks", tags=["stocks"])
logger = logging.getLogger(__name__)
# Parallel readers for one company page; kept below the connection pool (pool + overflow).
PAGE_WORKERS = 4

DbConnection = Annotated[Connection, Depends(get_connection)]
Ticker = Annotated[str, Path(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&.\-]+$",
                             description="NSE symbol by default; BSE scrip id or code with exchange=BSE")]
ExchangeParam = Annotated[Exchange | None, Query(description="Restrict lookup to one exchange")]

_ERRORS = {
    404: {"model": ErrorResponse, "description": "Not found"},
    422: {"model": ErrorResponse, "description": "Invalid input"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
}


def _company_id(conn: Connection, ticker: str):  # noqa: ANN202
    repo = CompanyRepository(conn)
    company_id = repo.find_company_id_by_ticker(ticker.strip(), None)
    if company_id is None:
        raise NotFoundError(f"No company found for ticker '{ticker}'.")
    return company_id, repo.get_company(company_id)["company_name"]


@router.get("", response_model=OverviewResponse)
def list_companies(conn: DbConnection) -> OverviewResponse:
    """Every company in Power BI (tracked), with its latest close, day change and 30 days of news tone."""
    return OverviewService(conn, get_settings().max_tracked_companies).companies()


@router.get("/search", response_model=SearchResponse, responses=_ERRORS)
def search_companies(
    conn: DbConnection,
    q: Annotated[str, Query(min_length=2, max_length=64,
                            description="Company name, alias, NSE/BSE symbol, BSE code or ISIN")],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> SearchResponse:
    """Search companies by name, abbreviation, ticker, BSE scrip code or ISIN.

    Typos are tolerated (trigram matching). An empty `results` list is a normal answer.
    """
    return CompanyService(conn).search(q, limit)


@router.get("/{ticker}", response_model=CompanyDetail, responses=_ERRORS)
def get_company(conn: DbConnection, ticker: Ticker, exchange: ExchangeParam = None) -> CompanyDetail:
    """Company details with all its exchange listings."""
    return CompanyService(conn).get_by_ticker(ticker, exchange)


@router.get("/{ticker}/prices", response_model=PriceHistoryResponse, responses=_ERRORS)
def get_prices(
    conn: DbConnection,
    ticker: Ticker,
    exchange: ExchangeParam = None,
    start: Annotated[date | None, Query(description="Default: one year before `end`")] = None,
    end: Annotated[date | None, Query(description="Default: today")] = None,
) -> PriceHistoryResponse:
    """Daily OHLCV for one listing (NSE unless `exchange=BSE`), oldest first.

    Each row names the provider that supplied it. End-of-day, delayed data.
    """
    return MarketQueryService(conn).prices(ticker, exchange, start, end)


@router.get("/{ticker}/financials", response_model=FinancialsResponse, responses=_ERRORS)
def get_financials(
    conn: DbConnection,
    ticker: Ticker,
    period_type: Annotated[Literal["quarterly", "annual"], Query()] = "quarterly",
    limit: Annotated[int, Query(ge=1, le=40)] = 8,
) -> FinancialsResponse:
    """Reported revenue, net profit, EPS, shareholders' equity and shares outstanding, newest first.

    Metrics the source did not report are `null`; nothing is estimated.
    """
    return MarketQueryService(conn).financials(ticker, period_type, limit)


@router.get("/{ticker}/news", response_model=NewsResponse, responses=_ERRORS)
def get_news(
    conn: DbConnection,
    ticker: Ticker,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    min_relevance: Annotated[float, Query(
        ge=0, le=1, description="1.0 headline, 0.85 short name, 0.6 description only")] = 0.5,
    before: Annotated[datetime | None, Query(description="Page cursor: `next_before` from the previous page")] = None,
) -> NewsResponse:
    """News and exchange announcements about a company, newest first.

    Each item links to the original publisher; only the headline and the publisher's own
    short description are stored.
    """
    return ContentQueryService(conn).news(ticker, limit, min_relevance, before)


@router.get("/{ticker}/reports", response_model=ReportsResponse, responses=_ERRORS)
def get_reports(
    conn: DbConnection,
    ticker: Ticker,
    document_type: Annotated[
        Literal["annual_report", "quarterly_results", "investor_presentation", "exchange_filing",
                "earnings_transcript", "other_disclosure"] | None, Query()] = None,
) -> ReportsResponse:
    """Company documents (annual reports, results filings) and whether their text has been extracted."""
    return ContentQueryService(conn).reports(ticker, document_type)


@router.get("/{ticker}/sentiment", response_model=SentimentResponse, responses=_ERRORS)
def get_sentiment(
    conn: DbConnection,
    ticker: Ticker,
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> SentimentResponse:
    """Daily news sentiment for a company (AI-rated), oldest first.

    Each finished day is scored once from the articles published that day (India time)
    and never changed afterwards. Sentiment describes news tone, not future prices.
    """
    return ContentQueryService(conn).sentiment(ticker, days)


@router.get("/{ticker}/analysis", response_model=AnalysisResponse, responses=_ERRORS)
def get_analysis(conn: DbConnection, ticker: Ticker) -> AnalysisResponse:
    """AI summaries of the company's reports: key points and risks, each citing report pages."""
    return ContentQueryService(conn).analysis(ticker)


@router.post("/{ticker}/refresh", response_model=RefreshResponse, status_code=202,
             responses={**_ERRORS, 200: {"model": RefreshResponse,
                                         "description": "A refresh finished moments ago; it is returned as-is"}})
def refresh(
    conn: DbConnection, ticker: Ticker, service: JobServiceDep, background: BackgroundTasks, response: Response,
) -> RefreshResponse:
    """Collect the latest prices, news and filings for one company, then run the AI analysis.

    Returns at once with a job to poll (`poll_url`). Only one refresh per company runs at a
    time, and one that finished within the cooldown (15 minutes by default) is returned
    instead of starting another.
    """
    company_id, _ = _company_id(conn, ticker)
    job, created = service.request_refresh(company_id)
    if created:
        background.add_task(service.run, job["job_id"])
    if job["status"] not in ("pending", "running"):
        response.status_code = 200
    return RefreshResponse(**job, created=created, poll_url=f"/jobs/{job['job_id']}")


@router.get("/{ticker}/jobs", response_model=JobListResponse, responses=_ERRORS)
def recent_jobs(
    conn: DbConnection, ticker: Ticker, service: JobServiceDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> JobListResponse:
    """The company's latest refreshes, newest first (shows when its data was last updated)."""
    company_id, name = _company_id(conn, ticker)
    jobs = [Job(**j) for j in service.recent(company_id, limit)]
    return JobListResponse(company_id=company_id, company_name=name, count=len(jobs), jobs=jobs)


@router.get("/{ticker}/summary", response_model=SummaryResponse, responses=_ERRORS)
def get_summary(conn: DbConnection, ticker: Ticker, exchange: ExchangeParam = None) -> SummaryResponse:
    """Latest price, 52-week range and key ratios (market cap, P/E, P/B, dividend yield, ROE, growth).

    Worked out on request from stored prices and reported financials; each value says
    what it was based on, and missing ones say why.
    """
    return MarketQueryService(conn).summary(ticker, exchange)


@router.get("/{ticker}/page", response_model=CompanyPage, responses=_ERRORS)
def get_company_page(conn: DbConnection, ticker: Ticker, service: JobServiceDep) -> CompanyPage:
    """Everything the website's company page shows, in one request: details, key numbers,
    a year of prices, results, news, tone, report summaries, documents and the latest refresh.

    Sections are read in parallel, each over its own pooled connection: the database is a
    round trip away from the API, so running them one after another took several seconds.
    A section that fails is left out (and named in `missing`) rather than failing the page.
    """
    company = CompanyService(conn).get_by_ticker(ticker)
    conn.rollback()
    engine = get_engine()
    settings = get_settings()

    def on_own_connection(fn):  # noqa: ANN001, ANN202
        def run():  # noqa: ANN202
            with engine.connect() as c:
                return fn(c)
        return run

    loaders = {
        "summary": on_own_connection(lambda c: MarketQueryService(c).summary(ticker, None)),
        "prices": on_own_connection(lambda c: MarketQueryService(c).prices(ticker, None, None, None)),
        "quarterly": on_own_connection(lambda c: MarketQueryService(c).financials(ticker, "quarterly", 8)),
        "annual": on_own_connection(lambda c: MarketQueryService(c).financials(ticker, "annual", 5)),
        "news": on_own_connection(lambda c: ContentQueryService(c).news(ticker, 20, 0.5, None)),
        "sentiment": on_own_connection(lambda c: ContentQueryService(c).sentiment(ticker, 30)),
        "analysis": on_own_connection(lambda c: ContentQueryService(c).analysis(ticker)),
        "reports": on_own_connection(lambda c: ContentQueryService(c).reports(ticker, None)),
        "last_job": lambda: service.recent(company.company_id, 1),
        "tracked_count": lambda: TrackingService(engine, settings.max_tracked_companies).count(),
    }
    results, missing = {}, []
    with ThreadPoolExecutor(max_workers=PAGE_WORKERS) as pool:
        futures = {name: pool.submit(fn) for name, fn in loaders.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception:  # noqa: BLE001
                logger.exception("page_section_failed", extra={"ticker": ticker, "section": name})
                missing.append(name)
                results[name] = None

    jobs = results.pop("last_job")
    count = results.pop("tracked_count")
    return CompanyPage(
        company=company, **results,
        last_job=Job(**jobs[0]) if jobs else None,
        tracking=Tracking(tracked_count=count if count is not None else 0, cap=settings.max_tracked_companies),
        missing=missing,
    )


@router.post("/{ticker}/track", response_model=TrackResponse, responses={
    **_ERRORS, 409: {"model": ErrorResponse, "description": "Power BI already follows the most companies allowed"}})
def track_company(
    conn: DbConnection, ticker: Ticker, service: JobServiceDep, background: BackgroundTasks,
) -> TrackResponse:
    """Add a company to Power BI: it is then collected every day and analysed by AI.

    Anyone can add one, up to `MAX_TRACKED_COMPANIES`. A newly added company gets a full
    refresh straight away (AI included) when there's room to run one.
    """
    company_id, name = _company_id(conn, ticker)
    conn.rollback()   # release this read-only transaction before taking the tracking lock
    settings = get_settings()
    created, count = TrackingService(get_engine(), settings.max_tracked_companies).track(company_id)
    job_id = None
    if created:
        job_id = service.create_company_job(company_id, "api")
        if job_id:
            background.add_task(service.run, job_id)
    return TrackResponse(company_id=company_id, company_name=name, is_tracked=True, created=created,
                         tracked_count=count, cap=settings.max_tracked_companies, job_id=job_id)


@router.delete("/{ticker}/track", response_model=UntrackResponse, responses={
    **_ERRORS, 409: {"model": ErrorResponse, "description": "One of the starting companies, which stay in Power BI"}})
def untrack_company(conn: DbConnection, ticker: Ticker) -> UntrackResponse:
    """Remove a company from Power BI: it stops being collected daily and analysed by AI.

    Its stored prices, results, news and AI ratings are kept, so adding it back later carries on
    from there. The starting companies can't be removed.
    """
    company_id, name = _company_id(conn, ticker)
    conn.rollback()
    settings = get_settings()
    removed, count = TrackingService(get_engine(), settings.max_tracked_companies).untrack(company_id)
    return UntrackResponse(company_id=company_id, company_name=name, is_tracked=False, removed=removed,
                           tracked_count=count, cap=settings.max_tracked_companies)
