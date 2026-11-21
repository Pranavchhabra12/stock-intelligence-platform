"""Read-side rules for prices and financials (what the API returns)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.engine import Connection

from backend.core.errors import AppError, NotFoundError
from backend.database.market_repository import MarketDataRepository
from backend.database.repositories import CompanyRepository
from backend.schemas.market import (
    FinancialPeriod,
    FinancialsResponse,
    ListingRef,
    MetricInfo,
    PriceHistoryResponse,
    PriceRow,
    SourceInfo,
)

MAX_RANGE_DAYS = 366 * 10


class InvalidRangeError(AppError):
    status_code = 422
    code = "validation_error"


class MarketQueryService:
    def __init__(self, conn: Connection) -> None:
        self.companies = CompanyRepository(conn)
        self.market = MarketDataRepository(conn)

    def _company(self, ticker: str, exchange: str | None) -> tuple:
        company_id = self.companies.find_company_id_by_ticker(ticker.strip(), exchange)
        if company_id is None:
            where = f" on {exchange}" if exchange else ""
            raise NotFoundError(f"No company found for ticker '{ticker}'{where}.")
        return company_id, self.companies.get_company(company_id)["company_name"]

    def _source(self, source_id: int | None) -> SourceInfo | None:
        info = self.market.source_info(source_id) if source_id else None
        if not info:
            return None
        return SourceInfo(code=info["source_code"], name=info["source_name"], attribution=info["attribution_text"])

    def prices(
        self, ticker: str, exchange: str | None, start: date | None, end: date | None
    ) -> PriceHistoryResponse:
        end = end or date.today()
        start = start or end - timedelta(days=365)
        if start > end:
            raise InvalidRangeError("start must be on or before end.")
        if (end - start).days > MAX_RANGE_DAYS:
            raise InvalidRangeError("Date range can be at most 10 years.")

        company_id, name = self._company(ticker, exchange)
        listing = self.market.pick_listing(company_id, exchange)
        if listing is None:
            raise NotFoundError(f"No active {exchange or ''} listing for '{ticker}'.".replace("  ", " "))

        rows = self.market.prices(listing["listing_id"], start, end)
        bases = {r["price_basis"] for r in rows}
        source_ids = sorted({r["source_id"] for r in rows})
        return PriceHistoryResponse(
            company_id=company_id,
            company_name=name,
            listing=ListingRef(**{k: listing[k] for k in ListingRef.model_fields}),
            start=start,
            end=end,
            price_basis=(bases.pop() if len(bases) == 1 else "mixed") if rows else None,
            sources=[s for s in (self._source(sid) for sid in source_ids) if s],
            count=len(rows),
            prices=[
                PriceRow(
                    trade_date=r["trade_date"], source=r["source_code"], open=r["open_price"],
                    high=r["high_price"], low=r["low_price"], close=r["close_price"],
                    adj_close=r["adj_close"], volume=r["volume"],
                )
                for r in rows
            ],
        )

    def financials(self, ticker: str, period_type: str, limit: int) -> FinancialsResponse:
        company_id, name = self._company(ticker, None)
        definitions = self.market.metric_definitions(reported_only=True)
        rows = self.market.financial_periods(company_id, period_type, limit)

        periods = []
        for r in rows:
            label = (f"Q{r['fiscal_quarter']} FY{r['fiscal_year']}" if r["period_type"] == "quarterly"
                     else f"FY{r['fiscal_year']}")
            # Every reported metric appears; missing ones are null, never guessed.
            metrics = {code: (float(r["metrics"][code]) if code in r["metrics"] else None) for code in definitions}
            periods.append(FinancialPeriod(
                label=label, period_type=r["period_type"], period_end=r["period_end"],
                fiscal_year=r["fiscal_year"], fiscal_quarter=r["fiscal_quarter"],
                consolidation=r["consolidation"], metrics=metrics,
            ))

        return FinancialsResponse(
            company_id=company_id,
            company_name=name,
            period_type=period_type,  # type: ignore[arg-type]
            source=self._source(rows[0]["source_id"] if rows else None),
            metric_definitions={k: MetricInfo(**v) for k, v in definitions.items()},
            periods=periods,
        )
