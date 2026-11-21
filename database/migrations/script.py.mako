"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- write SQL here
        """
    )


def downgrade() -> None:
    op.execute(
        """
        -- reverse the upgrade here
        """
    )
