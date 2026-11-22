"""Run the schedules on your own machine with APScheduler (the hosted demo uses
GitHub Actions instead, because free Render instances sleep when idle).

    python -m backend.scheduler.local

- weekdays 19:30 IST: the daily run (prices, news, filings, documents, AI)
- weekdays 09:00-19:00 IST, on the hour: the feeds run (no prices)

Jobs never overlap: a run that is still going makes the next one a no-op.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.scheduler import run_once

logger = logging.getLogger(__name__)
TIMEZONE = "Asia/Kolkata"


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(run_once.main, CronTrigger(day_of_week="mon-fri", hour=19, minute=30, timezone=TIMEZONE),
                      kwargs={"argv": ["--trigger", "schedule"]}, id="daily_run", max_instances=1, coalesce=True)
    scheduler.add_job(run_once.main, CronTrigger(day_of_week="mon-fri", hour="9-19", minute=0, timezone=TIMEZONE),
                      kwargs={"argv": ["--feeds", "--trigger", "schedule"]}, id="feeds_run", max_instances=1,
                      coalesce=True)
    return scheduler


def main() -> None:
    configure_logging(get_settings().log_level)
    scheduler = build_scheduler()
    for job in scheduler.get_jobs():
        logger.info("scheduled", extra={"job": job.id, "trigger": str(job.trigger)})
    scheduler.start()


if __name__ == "__main__":
    main()
