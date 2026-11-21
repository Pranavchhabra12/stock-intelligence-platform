"""Stock and company endpoints: search, details, prices and financials."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.engine import Connection

from backend.database.connection import get_connection
from backend.schemas.company import CompanyDetail, Exchange, SearchResponse
from backend.schemas.content import NewsResponse, ReportsResponse
from backend.schemas.errors import ErrorResponse
from backend.schemas.market import FinancialsResponse, PriceHistoryResponse
from backend.services.company_service import CompanyService
from backend.services.content_query_service import ContentQueryService
from backend.services.market_query_service import MarketQueryService

router = APIRouter(prefix="/stocks", tags=["stocks"])

DbConnection = Annotated[Connection, Depends(get_connection)]
Ticker = Annotated[str, Path(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&.\-]+$",
                             description="NSE symbol by default; BSE scrip id or code with exchange=BSE")]
ExchangeParam = Annotated[Exchange | None, Query(description="Restrict lookup to one exchange")]

_ERRORS = {
    404: {"model": ErrorResponse, "description": "Not found"},
    422: {"model": ErrorResponse, "description": "Invalid input"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
}


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
    min_relevance: Annotated[float, Query(ge=0, le=1, description="1.0 named in headline, 0.85 by short name, 0.6 only in the description")] = 0.5,
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
