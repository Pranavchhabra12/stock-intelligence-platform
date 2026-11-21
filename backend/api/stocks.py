"""Stock and company endpoints: search, details, prices and financials."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.engine import Connection

from backend.database.connection import get_connection
from backend.schemas.company import CompanyDetail, Exchange, SearchResponse
from backend.schemas.errors import ErrorResponse
from backend.schemas.market import FinancialsResponse, PriceHistoryResponse
from backend.services.company_service import CompanyService
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
