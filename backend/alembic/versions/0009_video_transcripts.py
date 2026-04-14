"""Add mux_playback_id to lessons; create lesson_transcripts table

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("mux_playback_id", sa.String(255), nullable=True),
    )

    op.create_table(
        "lesson_transcripts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("vtt_key", sa.String(512), nullable=False),
        sa.Column("plain_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lesson_id", name="uq_lesson_transcripts_lesson_id"),
    )
    op.create_index(
        "ix_lesson_transcripts_lesson_id", "lesson_transcripts", ["lesson_id"]
    )


def downgrade() -> None:
    op.drop_table("lesson_transcripts")
    op.drop_column("lessons", "mux_playback_id")
