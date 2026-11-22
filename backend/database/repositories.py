"""SQL access for master data. All SQL lives here; services never write SQL."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

_LISTING_COLUMNS = """
    l.listing_id, l.company_id, l.exchange, l.symbol, l.exchange_code,
    l.isin, l.series, l.currency, l.is_active
"""

# Ranking: exact identifier > exact alias > alias prefix > trigram similarity.
# `operator(extensions.%)` is pg_trgm's similarity test (threshold 0.3 by default)
# and can use the GIN index on alias_norm.
_SEARCH_SQL = text(
    """
    with matches as (
        select l.company_id, 1.0::float as score
        from app.company_listings l
        where l.is_active
          and (l.symbol = :q_upper or l.exchange_code = :q_upper or l.isin = :q_upper)
        union all
        select a.company_id,
               case
                 when a.alias_norm = :q_norm then 0.95
                 when a.alias_norm like :q_prefix then 0.90
                 else extensions.similarity(a.alias_norm, :q_norm) * 0.85
               end::float as score
        from app.company_aliases a
        where a.alias_norm = :q_norm
           or a.alias_norm like :q_prefix
           or a.alias_norm operator(extensions.%) :q_norm
    )
    select c.company_id, c.company_name, c.sector, c.industry, c.is_tracked,
           round(max(m.score)::numeric, 3)::float as score
    from matches m
    join app.companies c on c.company_id = m.company_id
    where c.is_active
    group by c.company_id, c.company_name, c.sector, c.industry, c.is_tracked
    -- tracked companies first among equally good matches
    order by score desc, c.is_tracked desc, c.company_name
    limit :limit
    """
)


class CompanyRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def search(self, q_upper: str, q_norm: str, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            _SEARCH_SQL,
            {"q_upper": q_upper, "q_norm": q_norm, "q_prefix": q_norm + "%", "limit": limit},
        ).mappings()
        return [dict(r) for r in rows]

    def listings_for(self, company_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]:
        if not company_ids:
            return {}
        stmt = text(
            f"""
            select {_LISTING_COLUMNS}
            from app.company_listings l
            where l.company_id in :ids
            order by l.exchange desc, l.symbol   -- NSE before BSE
            """
        ).bindparams(bindparam("ids", expanding=True))
        grouped: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for row in self.conn.execute(stmt, {"ids": list(company_ids)}).mappings():
            grouped[row["company_id"]].append(dict(row))
        return grouped

    def find_company_id_by_ticker(self, ticker: str, exchange: str | None) -> UUID | None:
        """Resolve a ticker to a company.

        With an exchange: NSE matches the symbol; BSE matches the scrip id or code.
        Without one: NSE symbol first, then BSE scrip id or code, then ISIN.
        """
        stmt = text(
            """
            select l.company_id
            from app.company_listings l
            where l.is_active
              and (cast(:exchange as text) is null or l.exchange = :exchange)
              and (l.symbol = :t
                   or (l.exchange = 'BSE' and l.exchange_code = :t)
                   or (cast(:exchange as text) is null and l.isin = :t))
            order by
              case
                when l.exchange = 'NSE' and l.symbol = :t then 0
                when l.exchange = 'BSE' then 1
                else 2
              end
            limit 1
            """
        )
        return self.conn.execute(stmt, {"t": ticker.upper(), "exchange": exchange}).scalar()

    def get_company(self, company_id: UUID) -> dict[str, Any] | None:
        row = self.conn.execute(
            text(
                """
                select company_id, company_name, legal_name, cin, sector, industry,
                       description, website, is_active, is_tracked, tracked_at, tracked_via,
                       untracked_at, updated_at
                from app.companies
                where company_id = :id
                """
            ),
            {"id": company_id},
        ).mappings().first()
        return dict(row) if row else None

    def aliases_for(self, company_id: UUID) -> list[str]:
        rows = self.conn.execute(
            text(
                """
                select alias from app.company_aliases
                where company_id = :id
                order by alias_type, alias
                """
            ),
            {"id": company_id},
        )
        return [r[0] for r in rows]

    def ping(self) -> bool:
        return self.conn.execute(text("select 1")).scalar() == 1
