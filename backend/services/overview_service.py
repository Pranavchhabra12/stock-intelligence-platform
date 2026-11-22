"""Every tracked company in one call: latest close, day change and recent news tone."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.schemas.company import CompanyOverview, OverviewResponse, ToneDay
from backend.services.ai_analysis import METHODOLOGY_VERSION

TONE_DAYS = 30


class OverviewService:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def companies(self, today: date | None = None) -> OverviewResponse:
        today = today or date.today()
        rows = self.conn.execute(text(
            """
            select c.company_id, c.company_name, c.sector, l.exchange, l.symbol,
                   p.trade_date, p.close_price, p.prev_close
            from app.companies c
            join lateral (
              select listing_id, exchange, symbol from app.company_listings
              where company_id = c.company_id and is_active order by exchange desc limit 1
            ) l on true
            left join lateral (
              select trade_date, close_price,
                     lead(close_price) over (order by trade_date desc) as prev_close
              from app.daily_prices where listing_id = l.listing_id
              order by trade_date desc limit 2
            ) p on true
            where c.is_active
            """
        )).mappings().all()
        latest = {}
        for r in rows:   # the lateral gives two rows per company; keep the newest
            if r["company_id"] not in latest or (r["trade_date"] and r["trade_date"] >
                                                 (latest[r["company_id"]]["trade_date"] or date.min)):
                latest[r["company_id"]] = r

        tone = defaultdict(list)
        for t in self.conn.execute(text(
            """
            select company_id, as_of_date, sentiment_score, article_count from app.sentiment_history
            where methodology_version = :mv and as_of_date >= :since order by as_of_date
            """
        ), {"mv": METHODOLOGY_VERSION, "since": today - timedelta(days=TONE_DAYS)}).mappings():
            tone[t["company_id"]].append(ToneDay(date=t["as_of_date"], score=float(t["sentiment_score"]),
                                                 article_count=t["article_count"]))

        companies = []
        for r in sorted(latest.values(), key=lambda r: r["company_name"]):
            close = float(r["close_price"]) if r["close_price"] is not None else None
            prev = float(r["prev_close"]) if r["prev_close"] is not None else None
            companies.append(CompanyOverview(
                company_id=r["company_id"], company_name=r["company_name"], sector=r["sector"],
                exchange=r["exchange"], symbol=r["symbol"], trade_date=r["trade_date"], close=close,
                change_pct=round((close - prev) / prev * 100, 2) if close and prev else None,
                tone_30d=tone.get(r["company_id"], []),
            ))
        return OverviewResponse(count=len(companies), tone_days=TONE_DAYS, companies=companies)
