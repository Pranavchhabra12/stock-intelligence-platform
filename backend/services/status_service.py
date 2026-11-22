"""System status: is each part of the platform working, and how fresh is its data?

Everything here is read from the database (no calls to outside providers), so the status
page is cheap to load and can't be used to spend API quotas. Live provider checks run in
the daily "Live data check" workflow instead.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

from backend.core.config import Settings

STARTED_AT = datetime.now(UTC)


@dataclass
class Check:
    name: str
    status: str          # ok | warning | failed
    detail: str
    last_success: datetime | None = None


def _age(ts: datetime | None, now: datetime) -> str:
    if ts is None:
        return "never"
    hours = (now - ts).total_seconds() / 3600
    if hours < 1:
        return f"{max(1, round(hours * 60))} min ago"
    if hours < 48:
        return f"{round(hours)} hours ago" if round(hours) != 1 else "1 hour ago"
    return f"{round(hours / 24)} days ago"


def _fresh(ts: datetime | None, now: datetime, ok_within: timedelta, warn_within: timedelta) -> str:
    if ts is None:
        return "failed"
    age = now - ts
    return "ok" if age <= ok_within else "warning" if age <= warn_within else "failed"


class StatusService:
    def __init__(self, engine: Engine, settings: Settings, now: datetime | None = None) -> None:
        self.engine = engine
        self.settings = settings
        self.now = now or datetime.now(UTC)

    def report(self) -> dict:
        started = time.perf_counter()
        try:
            with self.engine.connect() as conn:
                conn.execute(text("select 1"))
                db_ms = round((time.perf_counter() - started) * 1000)
                facts = self._facts(conn)
        except Exception as exc:  # noqa: BLE001 - the status page must still answer
            return self._result([Check("Database", "failed", f"Can't reach the database ({type(exc).__name__}).")],
                                {}, None)
        checks = [Check("Database", "ok", f"Answering in {db_ms} ms.", self.now)]
        checks += self._checks(facts)
        return self._result(checks, facts, db_ms)

    def _facts(self, conn) -> dict:  # noqa: ANN001
        one = lambda sql: conn.execute(text(sql)).scalar()  # noqa: E731
        jobs = {r["job_type"]: dict(r) for r in conn.execute(text(
            """
            select distinct on (job_type) job_type, status, finished_at, error
            from app.collection_jobs where finished_at is not null
            order by job_type, finished_at desc
            """
        )).mappings()}
        last_ok = {r["job_type"]: r["finished_at"] for r in conn.execute(text(
            """
            select job_type, max(finished_at) as finished_at from app.collection_jobs
            where status in ('completed', 'completed_with_errors') group by job_type
            """
        )).mappings()}
        return {
            "companies_listed": one("select count(*) from app.companies where is_active"),
            "companies_tracked": one("select count(*) from app.companies where is_tracked"),
            "latest_price_date": one(
                "select max(p.trade_date) from app.daily_prices p join app.company_listings l using (listing_id) "
                "join app.companies c using (company_id) where c.is_tracked"),
            "stale_price_companies": one(
                """
                select count(*) from app.companies c where c.is_tracked and coalesce((
                  select max(p.trade_date) from app.daily_prices p join app.company_listings l using (listing_id)
                  where l.company_id = c.company_id), date '1900-01-01') < current_date - 5
                """),
            "latest_news_at": one("select max(collected_at) from app.news_articles"),
            "news_last_24h": one(
                "select count(*) from app.news_articles where collected_at > now() - interval '24 hours'"),
            "latest_ai_at": one("select max(created_at) from app.ai_analyses where status = 'completed'"),
            "ai_rejected_7d": one(
                "select count(*) from app.ai_analyses "
                "where status = 'failed' and created_at > now() - interval '7 days'"),
            "ai_saved_7d": one(
                "select count(*) from app.ai_analyses "
                "where status = 'completed' and created_at > now() - interval '7 days'"),
            "latest_tone_day": one("select max(as_of_date) from app.sentiment_history"),
            "documents_failed": one("select count(*) from app.company_documents where extraction_status = 'failed'"),
            "jobs": jobs,
            "last_ok": last_ok,
            "results_fetch": dict(conn.execute(text(
                """
                select max(f.last_success_at) as last_success,
                       count(*) filter (where f.last_error is not null) as failing,
                       count(*) filter (where f.last_success_at is not null) as companies
                from app.provider_fetches f join app.data_sources s using (source_id)
                join app.companies c using (company_id)
                where s.source_code = 'indianapi' and c.is_tracked
                """)).mappings().one()),
            "fallback_rows_30d": one(
                "select count(*) from app.daily_prices p join app.data_sources s using (source_id) "
                "where s.source_code <> 'yfinance' and p.trade_date > current_date - 30"),
        }

    def _checks(self, f: dict) -> list[Check]:
        now, c = self.now, []
        day = timedelta(hours=30)

        price_day = f["latest_price_date"]
        price_ts = datetime(price_day.year, price_day.month, price_day.day, 10, tzinfo=UTC) if price_day else None
        stale = f["stale_price_companies"] or 0
        status = _fresh(price_ts, now, timedelta(days=4), timedelta(days=7))   # weekends and holidays
        if status == "ok" and stale:
            status = "warning"
        c.append(Check("Prices and results", status,
                       (f"Latest close {price_day:%d %b %Y}." if price_day else "No prices stored.")
                       + (f" {stale} tracked compan{'y has' if stale == 1 else 'ies have'} no price in 5 days."
                          if stale else "")
                       + (f" Backup sources supplied {f['fallback_rows_30d']} prices in the last 30 days."
                          if f["fallback_rows_30d"] else ""), price_ts))

        c.append(Check("News", _fresh(f["latest_news_at"], now, day, timedelta(days=3)),
                       f"Last new article {_age(f['latest_news_at'], now)}; {f['news_last_24h']} in the last 24 hours.",
                       f["latest_news_at"]))

        if self.settings.indianapi_key:
            r = f["results_fetch"]
            failing = r["failing"] or 0
            if r["last_success"] is None and not failing:
                c.append(Check("Company results (IndianAPI)", "warning",
                               "Set up, waiting for its first fetch: at the next daily run, or straight away "
                               "when Refresh is tapped on a company in Power BI."))
            else:
                status = "failed" if failing and not r["companies"] else "warning" if failing else \
                    _fresh(r["last_success"], now, timedelta(days=15), timedelta(days=30))
                c.append(Check("Company results (IndianAPI)", status,
                               f"Last fetched {_age(r['last_success'], now)}; up to date for {r['companies']} "
                               f"compan{'y' if r['companies'] == 1 else 'ies'}"
                               + (f", {failing} failing." if failing else ".")
                               + " Checked every 2 weeks, every 2 days while results are due.", r["last_success"]))

        if not self.settings.gemini_api_key:
            c.append(Check("AI (Gemini)", "warning", "No Gemini key is set, so AI tone and summaries are paused."))
        else:
            rejected, saved = f["ai_rejected_7d"] or 0, f["ai_saved_7d"] or 0
            status = _fresh(f["latest_ai_at"], now, day, timedelta(days=3))
            if status == "ok" and saved and rejected > saved * 0.2:
                status = "warning"
            c.append(Check("AI (Gemini)", status,
                           f"Last rating {_age(f['latest_ai_at'], now)}; {saved} saved and {rejected} rejected in "
                           f"7 days. Latest scored tone day: "
                           + (f"{f['latest_tone_day']:%d %b}." if f["latest_tone_day"] else "none yet."),
                           f["latest_ai_at"]))

        for job_type, name, window in (("scheduled_run", "Daily run (19:30 IST)", timedelta(hours=30)),
                                       ("feeds_run", "Hourly news run", timedelta(hours=3))):
            last, ok_at = f["jobs"].get(job_type), f["last_ok"].get(job_type)
            if last is None:
                c.append(Check(name, "warning", "Hasn't run yet."))
                continue
            status = _fresh(ok_at, now, window, window * 3)
            if status == "ok" and last["status"] != "completed":
                status = "warning"
            words = {"completed": "succeeded", "completed_with_errors": "partly succeeded", "failed": "failed"}
            detail = f"Last run {words.get(last['status'], last['status'])} {_age(last['finished_at'], now)}."
            if last["status"] != "completed" and last.get("error"):
                detail += f" {last['error'][:160]}"
            c.append(Check(name, status, detail, ok_at))

        if f["documents_failed"]:
            c.append(Check("Reports", "warning", f"{f['documents_failed']} report(s) couldn't be downloaded or read."))
        return c

    def _result(self, checks: list[Check], facts: dict, db_ms: int | None) -> dict:
        worst = "failed" if any(x.status == "failed" for x in checks) else \
            "warning" if any(x.status == "warning" for x in checks) else "ok"
        return {
            "status": worst,
            "checked_at": self.now,
            "api": {"version": (os.environ.get("RENDER_GIT_COMMIT") or "local")[:7],
                    "started_at": STARTED_AT, "region": os.environ.get("RENDER_REGION")},
            "database_ms": db_ms,
            "companies": {"listed": facts.get("companies_listed"), "tracked": facts.get("companies_tracked"),
                          "cap": self.settings.max_tracked_companies},
            "checks": [vars(x) for x in checks],
        }
