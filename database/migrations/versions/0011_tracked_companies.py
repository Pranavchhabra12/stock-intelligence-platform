"""Tracked companies: the whole NSE list is searchable, but only tracked companies are
collected every day, analysed by AI and included in Power BI.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-22
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table app.companies
          add column is_tracked  boolean not null default false,
          add column tracked_at  timestamptz,
          -- seed: the starting set; visitor: added from the website; admin: added by hand
          add column tracked_via text check (tracked_via in ('seed', 'visitor', 'admin')),
          add constraint companies_tracked_has_details
            check (not is_tracked or (tracked_at is not null and tracked_via is not null));

        -- Everything already in the database was the hand-picked starting set.
        update app.companies set is_tracked = true, tracked_at = now(), tracked_via = 'seed' where is_active;

        create index companies_tracked on app.companies (company_name) where is_tracked;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists app.companies_tracked;
        alter table app.companies
          drop constraint if exists companies_tracked_has_details,
          drop column if exists tracked_via,
          drop column if exists tracked_at,
          drop column if exists is_tracked;
        """
    )
