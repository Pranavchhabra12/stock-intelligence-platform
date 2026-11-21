"""Pin search_path on trigger functions (Supabase security advisor: function_search_path_mutable).

A function with a mutable search_path can be tricked into resolving names to
objects in another schema. Both functions only use fully qualified names or
pg_catalog built-ins, so an empty search_path is safe.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-22
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter function app.set_updated_at() set search_path = '';
        alter function app.reject_derived_metric() set search_path = '';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter function app.set_updated_at() reset search_path;
        alter function app.reject_derived_metric() reset search_path;
        """
    )
