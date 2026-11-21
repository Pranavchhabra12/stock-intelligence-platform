"""Security: row level security on every app table; no access for Supabase API roles.

The backend connects with a privileged role and is unaffected. Enabling RLS
with no policies means the Supabase `anon` and `authenticated` roles can read
nothing, even if the `app` schema is ever exposed by mistake.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = (
    "app.data_sources",
    "app.companies",
    "app.company_listings",
    "app.company_aliases",
    "app.listing_provider_ids",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"alter table {table} enable row level security;")

    # The anon/authenticated roles exist on Supabase but not on plain Postgres.
    op.execute(
        """
        do $$
        declare r text;
        begin
          foreach r in array array['anon', 'authenticated'] loop
            if exists (select 1 from pg_roles where rolname = r) then
              execute format('revoke all on schema app from %I', r);
              execute format('revoke all on all tables in schema app from %I', r);
              execute format('alter default privileges in schema app revoke all on tables from %I', r);
            end if;
          end loop;
        end $$;
        """
    )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"alter table {table} disable row level security;")
