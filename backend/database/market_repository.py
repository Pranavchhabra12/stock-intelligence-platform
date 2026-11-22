"""SQL access for prices, corporate actions and financials."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.providers.market_data.base import CorporateAction, FinancialPeriodData, ListingKey, PriceBar


def indian_fiscal_period(period_end: date) -> tuple[int, int]:
    """(fiscal_year, fiscal_quarter) for an Indian April-March year.

    FY2026 runs Apr 2025 - Mar 2026; Q1 = Apr-Jun ... Q4 = Jan-Mar.
    """
    fiscal_year = period_end.year if period_end.month <= 3 else period_end.year + 1
    fiscal_quarter = (period_end.month - 4) % 12 // 3 + 1
    return fiscal_year, fiscal_quarter


class MarketDataRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    # ---------- lookups ----------

    def source_id(self, source_code: str) -> int | None:
        return self.conn.execute(
            text("select source_id from app.data_sources where source_code = :c and is_active"),
            {"c": source_code},
        ).scalar()

    def source_info(self, source_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            text("select source_code, source_name, attribution_text from app.data_sources where source_id = :id"),
            {"id": source_id},
        ).mappings().first()
        return dict(row) if row else None

    def source_ids(self) -> dict[str, int]:
        rows = self.conn.execute(text("select source_code, source_id from app.data_sources where is_active"))
        return {r[0]: r[1] for r in rows}

    def listing_keys(self, company_id: UUID) -> list[tuple[UUID, ListingKey]]:
        """Active listings with every provider-specific symbol, NSE first."""
        rows = self.conn.execute(
            text(
                """
                select l.listing_id, l.exchange, l.symbol, l.isin, l.exchange_code,
                       coalesce(jsonb_object_agg(s.source_code, p.provider_symbol)
                                filter (where p.provider_symbol is not null), '{}'::jsonb) as overrides
                from app.company_listings l
                left join app.listing_provider_ids p on p.listing_id = l.listing_id
                left join app.data_sources s on s.source_id = p.source_id
                where l.company_id = :cid and l.is_active
                group by l.listing_id
                order by l.exchange desc
                """
            ),
            {"cid": company_id},
        ).mappings()
        return [
            (r["listing_id"], ListingKey(exchange=r["exchange"], symbol=r["symbol"], isin=r["isin"],
                                         exchange_code=r["exchange_code"], overrides=dict(r["overrides"])))
            for r in rows
        ]

    def last_trade_date(self, listing_id: UUID) -> date | None:
        return self.conn.execute(
            text("select max(trade_date) from app.daily_prices where listing_id = :id"), {"id": listing_id}
        ).scalar()

    def first_trade_date(self, listing_id: UUID) -> date | None:
        return self.conn.execute(
            text("select min(trade_date) from app.daily_prices where listing_id = :id"), {"id": listing_id}
        ).scalar()

    def pick_listing(self, company_id: UUID, exchange: str | None) -> dict[str, Any] | None:
        row = self.conn.execute(
            text(
                """
                select listing_id, exchange, symbol, exchange_code, isin
                from app.company_listings
                where company_id = :cid and is_active
                  and (cast(:ex as text) is null or exchange = :ex)
                order by exchange desc
                limit 1
                """
            ),
            {"cid": company_id, "ex": exchange},
        ).mappings().first()
        return dict(row) if row else None

    # ---------- writes ----------

    def upsert_prices(self, listing_id: UUID, bars: list[PriceBar], basis: str, source_id: int) -> int:
        if not bars:
            return 0
        self.conn.execute(
            text(
                """
                insert into app.daily_prices
                  (listing_id, trade_date, open_price, high_price, low_price, close_price,
                   adj_close, volume, price_basis, source_id)
                values
                  (:listing_id, :trade_date, :open, :high, :low, :close,
                   :adj_close, :volume, :basis, :source_id)
                on conflict (listing_id, trade_date) do update set
                  open_price = excluded.open_price, high_price = excluded.high_price,
                  low_price = excluded.low_price, close_price = excluded.close_price,
                  adj_close = excluded.adj_close, volume = excluded.volume,
                  price_basis = excluded.price_basis, source_id = excluded.source_id,
                  fetched_at = now()
                """
            ),
            [
                {"listing_id": listing_id, "trade_date": b.trade_date, "open": b.open, "high": b.high,
                 "low": b.low, "close": b.close, "adj_close": b.adj_close, "volume": b.volume,
                 "basis": basis, "source_id": source_id}
                for b in bars
            ],
        )
        return len(bars)

    def upsert_actions(self, listing_id: UUID, actions: list[CorporateAction], source_id: int) -> list[CorporateAction]:
        """Upsert actions; return the ones that were NEW (not seen before)."""
        new: list[CorporateAction] = []
        stmt = text(
            """
            insert into app.corporate_actions (listing_id, ex_date, action_type, ratio, amount, source_id)
            values (:listing_id, :ex_date, :action_type, :ratio, :amount, :source_id)
            on conflict (listing_id, ex_date, action_type) do update set
              ratio = excluded.ratio, amount = excluded.amount, fetched_at = now()
            returning (xmax = 0) as inserted
            """
        )
        for a in actions:
            inserted = self.conn.execute(
                stmt,
                {"listing_id": listing_id, "ex_date": a.ex_date, "action_type": a.action_type,
                 "ratio": a.ratio, "amount": a.amount, "source_id": source_id},
            ).scalar_one()
            if inserted:
                new.append(a)
        return new

    def upsert_period(self, company_id: UUID, period: FinancialPeriodData, source_id: int) -> int:
        fiscal_year, fiscal_quarter = indian_fiscal_period(period.period_end)
        period_id = self.conn.execute(
            text(
                """
                insert into app.financial_periods
                  (company_id, period_type, period_end, fiscal_year, fiscal_quarter, source_id)
                values (:cid, :ptype, :pend, :fy, :fq, :sid)
                on conflict (company_id, period_type, period_end, consolidation, source_id, revision)
                  do update set fetched_at = now()
                returning period_id
                """
            ),
            {"cid": company_id, "ptype": period.period_type, "pend": period.period_end, "fy": fiscal_year,
             "fq": fiscal_quarter if period.period_type == "quarterly" else None, "sid": source_id},
        ).scalar_one()
        if period.metrics:
            self.conn.execute(
                text(
                    """
                    insert into app.financial_metrics (period_id, metric_code, value)
                    values (:pid, :code, :value)
                    on conflict (period_id, metric_code) do update set value = excluded.value
                    """
                ),
                [{"pid": period_id, "code": c, "value": v} for c, v in period.metrics.items()],
            )
        return period_id

    def fill_company_profile(self, company_id: UUID, profile: dict[str, str | None]) -> None:
        """Fill empty profile fields only; never overwrite a value already there."""
        self.conn.execute(
            text(
                """
                update app.companies set
                  sector = coalesce(sector, :sector),
                  industry = coalesce(industry, :industry),
                  website = coalesce(website, :website),
                  description = coalesce(description, :description)
                where company_id = :cid
                """
            ),
            {"cid": company_id, **profile},
        )

    # ---------- reads for the API ----------

    def prices(self, listing_id: UUID, start: date, end: date) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            text(
                """
                select p.trade_date, p.open_price, p.high_price, p.low_price, p.close_price, p.adj_close,
                       p.volume, p.price_basis, p.source_id, s.source_code
                from app.daily_prices p
                join app.data_sources s on s.source_id = p.source_id
                where p.listing_id = :id and p.trade_date between :start and :end
                order by p.trade_date
                """
            ),
            {"id": listing_id, "start": start, "end": end},
        ).mappings()
        return [dict(r) for r in rows]

    def financial_periods(self, company_id: UUID, period_type: str, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            text(
                """
                -- One row per period. When two sources have it, IndianAPI wins (it reports
                -- consolidated figures and has the recent quarters), then the newest fetch.
                select * from (
                  select distinct on (p.period_end)
                         p.period_id, p.period_type, p.period_end, p.fiscal_year, p.fiscal_quarter,
                         p.consolidation, p.source_id,
                         coalesce(jsonb_object_agg(m.metric_code, m.value)
                                  filter (where m.metric_code is not null), '{}'::jsonb) as metrics
                  from app.financial_periods p
                  join app.data_sources s on s.source_id = p.source_id
                  left join app.financial_metrics m on m.period_id = p.period_id
                  where p.company_id = :cid and p.period_type = :ptype
                  group by p.period_id, s.source_code
                  order by p.period_end desc, (s.source_code = 'indianapi') desc, p.fetched_at desc
                ) one_per_period
                order by period_end desc
                limit :limit
                """
            ),
            {"cid": company_id, "ptype": period_type, "limit": limit},
        ).mappings()
        return [dict(r) for r in rows]

    def metric_definitions(self, reported_only: bool = True) -> dict[str, dict[str, str]]:
        rows = self.conn.execute(
            text(
                "select metric_code, label, unit from app.metric_definitions "
                "where not is_derived or not :reported_only order by metric_code"
            ),
            {"reported_only": reported_only},
        ).mappings()
        return {r["metric_code"]: {"label": r["label"], "unit": r["unit"]} for r in rows}
