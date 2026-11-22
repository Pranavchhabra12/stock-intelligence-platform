"""Run the pipeline once and record it as a job. Used by the schedules (GitHub Actions in
the hosted demo, APScheduler locally) and by hand.

    python -m backend.scheduler.run_once                 # daily run: every company, every step
    python -m backend.scheduler.run_once --feeds         # hourly run: news, filings, documents, AI
    python -m backend.scheduler.run_once INFY TCS        # refresh chosen companies

Exit code 1 if a run failed outright; partial failures are reported as warnings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.database.connection import get_engine
from backend.database.repositories import CompanyRepository
from backend.services.pipeline import JobLimits, JobService, default_steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the data pipeline once")
    parser.add_argument("tickers", nargs="*", help="refresh only these companies")
    parser.add_argument("--feeds", action="store_true", help="hourly run: skip prices")
    parser.add_argument("--trigger", choices=("schedule", "manual"),
                        default="schedule" if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else "manual")
    args = parser.parse_args(argv)
    if args.feeds and args.tickers:
        parser.error("--feeds runs over every company; don't give tickers")

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = get_engine()
    # GDELT only in the daily run: it is slow and often refuses cloud servers.
    service = JobService(engine, default_steps(engine, settings, use_gdelt=not args.feeds and not args.tickers),
                         JobLimits.from_settings(settings))

    if args.tickers:
        with engine.connect() as conn:
            repo = CompanyRepository(conn)
            ids = []
            for ticker in args.tickers:
                cid = repo.find_company_id_by_ticker(ticker, None)
                if cid is None:
                    print(f"Unknown ticker: {ticker}", file=sys.stderr)
                    return 1
                ids.append(cid)
        job_ids = [service.create_company_job(cid, args.trigger) for cid in ids]
    else:
        job_ids = [service.create_run("feeds_run" if args.feeds else "scheduled_run", args.trigger)]

    failed = False
    for job_id in job_ids:
        if job_id is None:
            print("A run of this kind is already in progress; nothing to do.", file=sys.stderr)
            continue
        job = service.run(job_id)
        summary = {"job_id": str(job_id), "status": job["status"],
                   "steps": {k: v["status"] for k, v in job["steps"].items()}}
        print(json.dumps(summary))
        if os.environ.get("GITHUB_ACTIONS") == "true":
            for name, step in job["steps"].items():
                for error in step["detail"].get("errors") or []:
                    print(f"::warning::{name}: {error}")
        failed |= job["status"] == "failed"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
