"""Collection jobs: on-demand company refreshes and scheduled runs, with their progress.

The table doubles as the job queue: a partial unique index allows only one
pending or running job per company and job type, so two clicks on "refresh"
can never start two jobs.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-22
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.collection_jobs (
          job_id        uuid primary key default gen_random_uuid(),
          job_type      text not null check (job_type in ('company_refresh', 'scheduled_run', 'feeds_run')),
          -- set for a company refresh; null for runs over every company
          company_id    uuid references app.companies (company_id) on delete cascade,
          triggered_by  text not null check (triggered_by in ('api', 'schedule', 'manual')),
          status        text not null default 'pending'
                          check (status in ('pending', 'running', 'completed', 'completed_with_errors', 'failed')),
          -- {"prices": {"status": "completed", "detail": {...}}, "news": {...}, ...}
          steps         jsonb not null default '{}'::jsonb,
          error         text check (length(error) <= 2000),
          attempts      smallint not null default 0 check (attempts >= 0),
          requested_at  timestamptz not null default now(),
          started_at    timestamptz,
          finished_at   timestamptz,
          constraint collection_jobs_company_refresh_has_company
            check (job_type <> 'company_refresh' or company_id is not null),
          constraint collection_jobs_times_in_order
            check ((started_at is null or started_at >= requested_at)
                   and (finished_at is null or finished_at >= coalesce(started_at, requested_at))),
          constraint collection_jobs_finished_when_done
            check ((status in ('pending', 'running')) = (finished_at is null))
        );
        -- one active job per company and type (runs over all companies use a fixed placeholder id)
        create unique index collection_jobs_one_active
          on app.collection_jobs (job_type, coalesce(company_id, '00000000-0000-0000-0000-000000000000'::uuid))
          where status in ('pending', 'running');
        create index collection_jobs_company_recent on app.collection_jobs (company_id, requested_at desc);
        create index collection_jobs_recent on app.collection_jobs (requested_at desc);

        alter table app.collection_jobs enable row level security;
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists app.collection_jobs;")
