"""Add public marketing fields to programs.

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("programs", sa.Column("marketing_summary", sa.Text(), nullable=True))
    op.add_column("programs", sa.Column("cover_image_url", sa.Text(), nullable=True))
    op.add_column(
        "programs",
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("programs", "display_order", server_default=None)


def downgrade() -> None:
    op.drop_column("programs", "display_order")
    op.drop_column("programs", "cover_image_url")
    op.drop_column("programs", "marketing_summary")
