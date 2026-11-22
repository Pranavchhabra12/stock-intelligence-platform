"""Removing a company from Power BI: remember when, so the website can safely refresh its
cached pages straight after a removal.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-22
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table app.companies add column untracked_at timestamptz")


def downgrade() -> None:
    op.execute("alter table app.companies drop column if exists untracked_at")
