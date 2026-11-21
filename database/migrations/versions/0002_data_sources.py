"""Data sources: registry of every provider with its licence details.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table app.data_sources (
          source_id              smallint generated always as identity primary key,
          source_code            text not null unique,
          source_name            text not null,
          source_type            text not null check (source_type in
                                   ('market_data', 'news', 'exchange_filing',
                                    'financial_report', 'reference', 'other')),
          base_url               text,
          terms_url              text,
          attribution_required   boolean not null default false,
          attribution_text       text,
          -- null = terms not yet reviewed
          redistribution_allowed boolean,
          license_notes          text,
          is_active              boolean not null default true,
          created_at             timestamptz not null default now(),
          updated_at             timestamptz not null default now()
        );

        comment on table app.data_sources is
          'Every external or manual source of data, with its licence and attribution details.';

        create trigger set_updated_at before update on app.data_sources
          for each row execute function app.set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists app.data_sources;")
