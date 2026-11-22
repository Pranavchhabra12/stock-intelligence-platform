"""When a rationed provider was last asked about a company, and whether it answered.

IndianAPI's free plan allows 500 requests a month, so results are fetched only when due; this
table makes "when did we last ask?" survive failures too (a failed call still counts).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-22
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.provider_fetches (
          company_id      uuid not null references app.companies (company_id) on delete cascade,
          source_id       smallint not null references app.data_sources (source_id),
          what            text not null,
          last_attempt_at timestamptz not null,
          last_success_at timestamptz,
          last_error      text,
          attempts        integer not null default 0,
          primary key (company_id, source_id, what)
        );
        alter table app.provider_fetches enable row level security;
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists app.provider_fetches")
