"""Add discussion_post_votes and discussion_flags tables

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── discussion_post_votes ──────────────────────────────────────────────────
    op.create_table(
        "discussion_post_votes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["discussion_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # One upvote per (post, user) pair — enforced at DB level
        sa.UniqueConstraint("post_id", "user_id", name="uq_discussion_post_votes_post_user"),
    )
    op.create_index("ix_discussion_post_votes_post_id", "discussion_post_votes", ["post_id"])
    op.create_index("ix_discussion_post_votes_user_id", "discussion_post_votes", ["user_id"])

    # ── discussion_flags ───────────────────────────────────────────────────────
    op.create_table(
        "discussion_flags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["post_id"], ["discussion_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Partial unique index: at most one *open* flag per (reporter, post) pair
    op.create_index(
        "uq_discussion_flags_open_per_user_post",
        "discussion_flags",
        ["post_id", "reporter_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    # Moderation queue hot-path indexes
    op.create_index("ix_discussion_flags_status", "discussion_flags", ["status"])
    op.create_index("ix_discussion_flags_created_at", "discussion_flags", ["created_at"])
    op.create_index("ix_discussion_flags_post_id", "discussion_flags", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_discussion_flags_post_id", "discussion_flags")
    op.drop_index("ix_discussion_flags_created_at", "discussion_flags")
    op.drop_index("ix_discussion_flags_status", "discussion_flags")
    op.drop_index("uq_discussion_flags_open_per_user_post", "discussion_flags")
    op.drop_table("discussion_flags")

    op.drop_index("ix_discussion_post_votes_user_id", "discussion_post_votes")
    op.drop_index("ix_discussion_post_votes_post_id", "discussion_post_votes")
    op.drop_table("discussion_post_votes")
