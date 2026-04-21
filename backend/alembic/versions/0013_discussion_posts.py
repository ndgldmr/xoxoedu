"""Create discussion_posts table

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discussion_posts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["discussion_posts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Hot-path compound index: lesson thread fetch filtered by parent, ordered by time
    op.create_index(
        "ix_discussion_posts_lesson_parent_created",
        "discussion_posts",
        ["lesson_id", "parent_id", "created_at"],
    )
    # Stand-alone indexes for individual predicate lookups
    op.create_index("ix_discussion_posts_lesson_id", "discussion_posts", ["lesson_id"])
    op.create_index("ix_discussion_posts_parent_id", "discussion_posts", ["parent_id"])
    op.create_index("ix_discussion_posts_created_at", "discussion_posts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_discussion_posts_created_at", "discussion_posts")
    op.drop_index("ix_discussion_posts_parent_id", "discussion_posts")
    op.drop_index("ix_discussion_posts_lesson_id", "discussion_posts")
    op.drop_index("ix_discussion_posts_lesson_parent_created", "discussion_posts")
    op.drop_table("discussion_posts")
