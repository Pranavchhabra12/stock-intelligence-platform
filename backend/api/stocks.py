"""Stock and company endpoints (Phase 1: search and company details)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.engine import Connection

from backend.database.connection import get_connection
from backend.schemas.company import CompanyDetail, Exchange, SearchResponse
from backend.schemas.errors import ErrorResponse
from backend.services.company_service import CompanyService

router = APIRouter(prefix="/stocks", tags=["stocks"])

DbConnection = Annotated[Connection, Depends(get_connection)]

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
def get_company(
    conn: DbConnection,
    ticker: Annotated[str, Path(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&.\-]+$",
                                description="NSE symbol by default; BSE scrip id or code with exchange=BSE")],
    exchange: Annotated[Exchange | None, Query(description="Restrict lookup to one exchange")] = None,
) -> CompanyDetail:
    """Company details with all its exchange listings."""
    return CompanyService(conn).get_by_ticker(ticker, exchange)
