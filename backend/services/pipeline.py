"""One pipeline, three triggers: a company refresh from the API, the daily scheduled
run, and the hourly feeds run.

Every run is a row in `collection_jobs`. Steps run in order and each one is
isolated: if prices fail, news and analysis still run. Progress is saved after
each step, so a client polling `GET /jobs/{job_id}` sees the job move along.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from backend.core.config import Settings
from backend.core.errors import AppError

logger = logging.getLogger(__name__)

StepStatus = str   # completed | completed_with_errors | failed | skipped
StepFn = Callable[[list[UUID] | None], tuple[StepStatus, dict[str, Any]]]

PLANS: dict[str, tuple[str, ...]] = {
    "company_refresh": ("prices", "news", "documents", "analysis"),
    "scheduled_run": ("prices", "news", "documents", "analysis"),
    "feeds_run": ("news", "documents", "analysis"),
}
ACTIVE = ("pending", "running")
_JOB_COLUMNS = """j.job_id, j.job_type, j.company_id, c.company_name, j.triggered_by, j.status, j.steps,
                  j.error, j.requested_at, j.started_at, j.finished_at"""


def _in_plan_order(job: dict) -> dict:
    """jsonb doesn't keep key order; show steps in the order they run."""
    plan = PLANS.get(job["job_type"], ())
    steps = job.get("steps") or {}
    job["steps"] = {name: steps[name] for name in sorted(steps, key=lambda n: plan.index(n) if n in plan else 99)}
    return job


class TooBusyError(AppError):
    status_code = 429
    code = "busy"


def overall_status(statuses: list[StepStatus]) -> str:
    ran = [s for s in statuses if s != "skipped"]
    if not ran or all(s == "completed" for s in ran):
        return "completed"
    return "failed" if all(s == "failed" for s in ran) else "completed_with_errors"


# ---------------------------------------------------------------- real steps

def default_steps(engine: Engine, settings: Settings, use_gdelt: bool = False) -> dict[str, StepFn]:
    """The production steps. Imports are local so the API starts without loading every provider."""

    def company_ids_or_all(ids: list[UUID] | None) -> list[UUID]:
        if ids is not None:
            return ids
        with engine.connect() as conn:
            return list(conn.execute(text("select company_id from app.companies where is_tracked "
                                          "order by company_name")).scalars())

    def prices(ids: list[UUID] | None) -> tuple[StepStatus, dict]:
        from backend.providers.market_data import build_market_data_provider
        from backend.services.market_data import MarketDataCollector

        key = settings.eodhd_api_key.get_secret_value() if settings.eodhd_api_key else None
        collector = MarketDataCollector(engine, build_market_data_provider(settings.market_data_provider_codes, key),
                                        backfill_years=settings.price_backfill_years)
        results = [collector.collect_company(cid) for cid in company_ids_or_all(ids)]
        detail = {"companies": len(results), "prices_upserted": sum(r.prices_upserted for r in results),
                  "periods_upserted": sum(r.periods_upserted for r in results),
                  "errors": [f"{r.company_name}: {e}" for r in results for e in r.errors][:10]}
        return overall_status([r.status for r in results]), detail

    def news(ids: list[UUID] | None) -> tuple[StepStatus, dict]:
        from backend.providers.news.gdelt import GdeltNewsAdapter
        from backend.providers.news.rss import RssAdapter
        from backend.services.news_collector import NewsCollector

        result = NewsCollector(engine, gdelt=GdeltNewsAdapter() if use_gdelt else None, rss=RssAdapter()).collect(ids)
        detail = {k: v for k, v in vars(result).items() if k != "errors"} | {"errors": result.errors[:10]}
        return result.status, detail

    def documents(ids: list[UUID] | None) -> tuple[StepStatus, dict]:
        from backend.services.document_service import DocumentService

        result = DocumentService(engine).ingest_pending(company_ids=ids)
        detail = {k: v for k, v in vars(result).items() if k != "errors"} | {"errors": result.errors[:10]}
        if not result.failed:
            return "completed", detail
        return ("completed_with_errors" if result.extracted else "failed"), detail

    def analysis(ids: list[UUID] | None) -> tuple[StepStatus, dict]:
        from backend.providers.ai.gemini import GeminiClient
        from backend.services.ai_analysis import AnalysisService

        if ids is not None:
            with engine.connect() as conn:
                tracked = conn.execute(text("select count(*) from app.companies "
                                            "where company_id = any(:ids) and is_tracked"), {"ids": ids}).scalar_one()
            if not tracked:
                return "skipped", {"reason": "AI tone and summaries start once the company is added to Power BI"}
        key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
        ai = GeminiClient(key, settings.gemini_model) if key else None
        result = AnalysisService(engine, ai, max_requests=settings.ai_max_requests_per_run).run(ids)
        detail = {k: v for k, v in vars(result).items() if k != "errors"} | {"errors": result.errors[:10],
                                                                              "model": ai.model if ai else None}
        if ai is None:
            return "skipped", detail | {"reason": "GEMINI_API_KEY is not set"}
        return result.status, detail

    return {"prices": prices, "news": news, "documents": documents, "analysis": analysis}


# ---------------------------------------------------------------- jobs

@dataclass
class JobLimits:
    cooldown: timedelta = timedelta(minutes=15)
    max_active: int = 3
    stale_after: timedelta = timedelta(minutes=45)

    @classmethod
    def from_settings(cls, settings: Settings) -> JobLimits:
        return cls(timedelta(minutes=settings.refresh_cooldown_minutes), settings.max_active_jobs,
                   timedelta(minutes=settings.job_stale_minutes))


class JobService:
    def __init__(self, engine: Engine, steps: dict[str, StepFn], limits: JobLimits | None = None) -> None:
        self.engine = engine
        self.steps = steps
        self.limits = limits or JobLimits()

    # ----- reading

    def get(self, job_id: UUID) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text(f"select {_JOB_COLUMNS} from app.collection_jobs j "
                                    "left join app.companies c using (company_id) where j.job_id = :id"),
                               {"id": job_id}).mappings().first()
        return _in_plan_order(dict(row)) if row else None

    def recent(self, company_id: UUID, limit: int = 5) -> list[dict]:
        with self.engine.connect() as conn:
            return [_in_plan_order(dict(r)) for r in conn.execute(text(
                f"select {_JOB_COLUMNS} from app.collection_jobs j left join app.companies c using (company_id) "
                "where j.company_id = :cid order by j.requested_at desc limit :limit"),
                {"cid": company_id, "limit": limit}).mappings()]

    # ----- creating

    def expire_stale(self) -> int:
        """Jobs left running by a restarted server would block their company forever; fail them."""
        with self.engine.begin() as conn:
            return conn.execute(text(
                """
                update app.collection_jobs
                set status = 'failed', finished_at = now(),
                    error = 'Stopped before finishing (the server restarted or the job took too long).'
                where status in ('pending', 'running')
                  and coalesce(started_at, requested_at) < now() - :stale
                """
            ), {"stale": self.limits.stale_after}).rowcount

    def request_refresh(self, company_id: UUID) -> tuple[dict, bool]:
        """Returns (job, created). An active job, or one that finished within the cooldown,
        is returned instead of starting another."""
        self.expire_stale()
        with self.engine.begin() as conn:
            existing = conn.execute(text(
                """
                select job_id from app.collection_jobs
                where company_id = :cid and job_type = 'company_refresh'
                  and (status in ('pending', 'running')
                       or (status in ('completed', 'completed_with_errors') and finished_at > now() - :cooldown))
                order by requested_at desc limit 1
                """
            ), {"cid": company_id, "cooldown": self.limits.cooldown}).scalar()
            if existing is None:
                active = conn.execute(text(
                    "select count(*) from app.collection_jobs where status in ('pending', 'running')")).scalar_one()
                if active >= self.limits.max_active:
                    raise TooBusyError("Too many refreshes are running right now. Try again in a few minutes.")
                existing = conn.execute(text(
                    """
                    insert into app.collection_jobs (job_type, company_id, triggered_by)
                    values ('company_refresh', :cid, 'api')
                    on conflict do nothing
                    returning job_id
                    """
                ), {"cid": company_id}).scalar()
                if existing is not None:
                    created = True
                else:   # another request created it a moment ago
                    existing = conn.execute(text(
                        "select job_id from app.collection_jobs where company_id = :cid "
                        "and job_type = 'company_refresh' and status in ('pending', 'running')"),
                        {"cid": company_id}).scalar_one()
                    created = False
            else:
                created = False
        return self.get(existing), created

    def create_company_job(self, company_id: UUID, triggered_by: str) -> UUID | None:
        """A refresh started by hand or by a schedule: no cooldown. None if one is already active."""
        self.expire_stale()
        with self.engine.begin() as conn:
            return conn.execute(text(
                "insert into app.collection_jobs (job_type, company_id, triggered_by) "
                "values ('company_refresh', :cid, :by) on conflict do nothing returning job_id"),
                {"cid": company_id, "by": triggered_by}).scalar()

    def create_run(self, job_type: str, triggered_by: str) -> UUID | None:
        """A run over every company. None if one of the same type is already active."""
        if job_type not in ("scheduled_run", "feeds_run"):
            raise ValueError(f"not a run type: {job_type}")
        self.expire_stale()
        with self.engine.begin() as conn:
            return conn.execute(text(
                "insert into app.collection_jobs (job_type, triggered_by) values (:t, :by) "
                "on conflict do nothing returning job_id"), {"t": job_type, "by": triggered_by}).scalar()

    # ----- running

    def run(self, job_id: UUID) -> dict | None:
        with self.engine.begin() as conn:
            job = conn.execute(text(
                """
                update app.collection_jobs set status = 'running', started_at = now(), attempts = attempts + 1
                where job_id = :id and status = 'pending'
                returning job_type, company_id
                """
            ), {"id": job_id}).mappings().first()
        if job is None:
            return None   # already taken, finished or expired
        ids = [job["company_id"]] if job["company_id"] else None
        statuses, errors = [], []
        for name in PLANS[job["job_type"]]:
            self._save_step(job_id, name, "running", {})
            try:
                status, detail = self.steps[name](ids)
            except Exception as exc:  # noqa: BLE001 - one broken step must not stop the others
                logger.exception("pipeline_step_crashed", extra={"job_id": str(job_id), "step": name})
                status, detail = "failed", {"errors": [f"{type(exc).__name__}: {str(exc)[:300]}"]}
            self._save_step(job_id, name, status, detail)
            statuses.append(status)
            if status in ("failed", "completed_with_errors"):
                errors.extend(f"{name}: {e}" for e in (detail.get("errors") or ["step failed"])[:3])
        final = overall_status(statuses)
        with self.engine.begin() as conn:
            conn.execute(text(
                "update app.collection_jobs set status = :s, finished_at = now(), error = :e where job_id = :id"),
                {"s": final, "e": "; ".join(errors)[:2000] or None, "id": job_id})
        logger.info("job_finished", extra={"job_id": str(job_id), "status": final})
        return self.get(job_id)

    def _save_step(self, job_id: UUID, name: str, status: StepStatus, detail: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(
                "update app.collection_jobs set steps = steps || jsonb_build_object(cast(:n as text), "
                "cast(:v as jsonb)) where job_id = :id"),
                {"n": name, "v": json.dumps({"status": status, "detail": detail}, default=str), "id": job_id})
