"""Foundation: schemas, pg_trgm extension, shared updated_at trigger function.

Revision ID: 0001
Revises:
Create Date: 2026-11-22
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Supabase already has an `extensions` schema; plain Postgres does not.
        create schema if not exists extensions;
        create extension if not exists pg_trgm with schema extensions;

        -- Application tables live in `app`, which Supabase's Data API does not expose.
        create schema if not exists app;

        create or replace function app.set_updated_at() returns trigger
        language plpgsql as $$
        begin
          new.updated_at := now();
          return new;
        end $$;
        """
    )


def downgrade() -> None:
    # The `app` schema and pg_trgm are left in place: the Alembic version table
    # lives in `app`, and other projects may rely on the extension.
    op.execute("drop function if exists app.set_updated_at();")
