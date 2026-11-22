"""Company identification and search: the business rules, independent of HTTP."""

from __future__ import annotations

import re

from sqlalchemy.engine import Connection

from backend.core.errors import AppError, NotFoundError
from backend.database.repositories import CompanyRepository
from backend.schemas.company import CompanyDetail, CompanySearchResult, SearchResponse

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_query(raw: str) -> str:
    """Same rule as the database's generated `alias_norm` column."""
    return _NON_ALNUM.sub(" ", raw.lower()).strip()


class InvalidQueryError(AppError):
    status_code = 422
    code = "validation_error"


class CompanyService:
    def __init__(self, conn: Connection) -> None:
        self.repo = CompanyRepository(conn)

    def search(self, raw_query: str, limit: int = 10) -> SearchResponse:
        query = raw_query.strip()
        q_norm = normalize_query(query)
        if len(q_norm.replace(" ", "")) < 2:
            raise InvalidQueryError(
                "Search needs at least 2 letters or digits.",
                [{"field": "query.q", "message": "too few letters or digits"}],
            )

        rows = self.repo.search(q_upper=query.upper(), q_norm=q_norm, limit=limit)
        listings = self.repo.listings_for([r["company_id"] for r in rows])
        results = [
            CompanySearchResult(**r, listings=listings.get(r["company_id"], []))
            for r in rows
        ]
        return SearchResponse(query=query, count=len(results), results=results)

    def get_by_ticker(self, ticker: str, exchange: str | None = None) -> CompanyDetail:
        company_id = self.repo.find_company_id_by_ticker(ticker.strip(), exchange)
        if company_id is None:
            where = f" on {exchange}" if exchange else ""
            raise NotFoundError(f"No company found for ticker '{ticker}'{where}.")
        return self.get_by_id(company_id)

    def get_by_id(self, company_id) -> CompanyDetail:  # noqa: ANN001 - UUID
        company = self.repo.get_company(company_id)
        if company is None:
            raise NotFoundError("Company not found.")
        listings = self.repo.listings_for([company_id]).get(company_id, [])
        via = company.pop("tracked_via", None)
        can_remove = bool(company["is_tracked"]) and via != "seed"
        return CompanyDetail(**company, can_remove=can_remove, listings=listings,
                             aliases=self.repo.aliases_for(company_id))
