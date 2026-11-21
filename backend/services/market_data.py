"""Collect prices, corporate actions, financials and profile for one company.

Idempotent and incremental:
- prices are fetched from the day after the last stored date (or a backfill
  window for a new listing) and upserted;
- providers are tried in order (Yahoo, then Upstox, then EODHD if configured);
  each row records the provider that actually supplied it;
- if a NEW split or bonus appears, the whole history is re-fetched, because the
  provider has rescaled every earlier price;
- each step runs in its own transaction, so one failing step does not undo the
  others, and the result records what failed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, text

from backend.database.market_repository import MarketDataRepository
from backend.providers.market_data.base import ListingKey, MarketDataProvider, ProviderError
from backend.providers.market_data.fallback import FallbackMarketDataProvider

logger = logging.getLogger(__name__)

Status = Literal["completed", "completed_with_errors", "failed"]


@dataclass
class CollectionResult:
    company_id: UUID
    company_name: str
    status: Status = "completed"
    prices_upserted: int = 0
    price_sources: dict[str, str] = field(default_factory=dict)   # listing -> source used
    actions_new: int = 0
    periods_upserted: int = 0
    full_refetch: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class MarketDataCollector:
    def __init__(
        self, engine: Engine, provider: MarketDataProvider, backfill_years: int = 5, today: date | None = None
    ) -> None:
        self.engine = engine
        self.chain = provider if isinstance(provider, FallbackMarketDataProvider) \
            else FallbackMarketDataProvider([provider])
        self.backfill_years = backfill_years
        self.today = today or date.today()

    @property
    def backfill_start(self) -> date:
        return self.today - timedelta(days=365 * self.backfill_years)

    def collect_company(self, company_id: UUID) -> CollectionResult:
        with self.engine.connect() as conn:
            name = conn.execute(
                text("select company_name from app.companies where company_id = :id"), {"id": company_id}
            ).scalar()
            repo = MarketDataRepository(conn)
            self.source_ids = repo.source_ids()
            listings = repo.listing_keys(company_id)

        result = CollectionResult(company_id=company_id, company_name=name or "?")
        if name is None:
            return self._fail(result, "company not found")
        if not listings:
            return self._fail(result, "company has no active listings")
        missing = [c for c in self.chain.source_codes if c not in self.source_ids]
        if missing:
            return self._fail(result, f"data sources not registered: {', '.join(missing)}")

        for listing_id, key in listings:
            self._collect_listing(listing_id, key, result)

        primary = listings[0][1]  # NSE when available
        self._step(result, "financials", lambda: self._collect_financials(company_id, primary, result))
        self._step(result, "profile", lambda: self._collect_profile(company_id, primary))

        if result.errors:
            got_data = result.prices_upserted or result.periods_upserted
            result.status = "completed_with_errors" if got_data else "failed"
        logger.info("collection_finished", extra={"company": result.company_name, "status": result.status,
                                                  "prices": result.prices_upserted, "errors": result.errors})
        return result

    # ---------- steps ----------

    def _collect_listing(self, listing_id: UUID, key: ListingKey, result: CollectionResult) -> None:
        label = f"{key.exchange}:{key.symbol}"
        new_actions: list = []

        def actions() -> None:
            source, fetched = self.chain.first_available(
                "corporate actions", lambda p: p.get_corporate_actions(key)
            )
            with self.engine.begin() as conn:
                new_actions.extend(
                    MarketDataRepository(conn).upsert_actions(listing_id, fetched, self.source_ids[source])
                )
            result.actions_new += len(new_actions)

        self._step(result, f"{label} corporate actions", actions)

        def prices() -> None:
            with self.engine.connect() as conn:
                repo = MarketDataRepository(conn)
                first, last = repo.first_trade_date(listing_id), repo.last_trade_date(listing_id)

            # A new split/bonus inside the stored range means the provider rescaled
            # earlier prices, so re-fetch everything to keep the series consistent.
            rescaled = any(
                a.action_type in ("split", "bonus") and first is not None and a.ex_date > first
                for a in new_actions
            )
            # Which date ranges to fetch, oldest first.
            ranges: list[tuple[date, date]] = []
            if last is None or rescaled:
                start = self.backfill_start if first is None else min(first, self.backfill_start)
                ranges.append((start, self.today))
                if rescaled:
                    result.full_refetch.append(label)
            else:
                # History that starts well after the backfill window has a gap at the
                # front (an earlier run got thin data): fill it.
                if first > self.backfill_start + timedelta(days=30):
                    ranges.append((self.backfill_start, first - timedelta(days=1)))
                ranges.append((last + timedelta(days=1), self.today))

            for range_start, range_end in ranges:
                if range_start > range_end:
                    continue
                history = self.chain.get_price_history(key, range_start, range_end)
                with self.engine.begin() as conn:
                    result.prices_upserted += MarketDataRepository(conn).upsert_prices(
                        listing_id, history.bars, history.price_basis, self.source_ids[history.source_code]
                    )
                if history.bars:
                    result.price_sources[label] = history.source_code

        self._step(result, f"{label} prices", prices)

    def _collect_financials(self, company_id: UUID, key: ListingKey, result: CollectionResult) -> None:
        source, periods = self.chain.first_available("financials", lambda p: p.get_financials(key))
        with self.engine.begin() as conn:
            repo = MarketDataRepository(conn)
            for period in periods:
                repo.upsert_period(company_id, period, self.source_ids[source])
        result.periods_upserted += len(periods)

    def _collect_profile(self, company_id: UUID, key: ListingKey) -> None:
        _, profile = self.chain.first_available("profile", lambda p: p.get_profile(key))
        if profile is None:
            return
        with self.engine.begin() as conn:
            MarketDataRepository(conn).fill_company_profile(company_id, vars(profile))

    # ---------- helpers ----------

    @staticmethod
    def _step(result: CollectionResult, label: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except ProviderError as exc:
            result.errors.append(f"{label}: {exc}")
        except Exception as exc:  # noqa: BLE001 - record and carry on with other steps
            logger.exception("collection_step_failed", extra={"step": label})
            result.errors.append(f"{label}: unexpected error ({type(exc).__name__})")

    @staticmethod
    def _fail(result: CollectionResult, message: str) -> CollectionResult:
        result.status = "failed"
        result.errors.append(message)
        return result
