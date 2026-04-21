"""Merge user_profiles into users table

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add profile columns to users (all nullable — existing rows get NULL)
    op.add_column("users", sa.Column("display_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("headline", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("social_links", postgresql.JSONB(), nullable=True))
    op.add_column("users", sa.Column("skills", postgresql.ARRAY(sa.Text()), nullable=True))

    # Copy existing profile data into users
    op.execute("""
        UPDATE users u
        SET
            display_name = p.display_name,
            avatar_url   = p.avatar_url,
            bio          = p.bio,
            headline     = p.headline,
            social_links = p.social_links,
            skills       = p.skills
        FROM user_profiles p
        WHERE p.user_id = u.id
    """)

    # Drop the now-redundant table
    op.drop_table("user_profiles")


def downgrade() -> None:
    # Recreate user_profiles and move data back
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("headline", sa.String(255), nullable=True),
        sa.Column("social_links", postgresql.JSONB(), nullable=True),
        sa.Column("skills", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.execute("""
        INSERT INTO user_profiles (user_id, display_name, avatar_url, bio, headline, social_links, skills)
        SELECT id, display_name, avatar_url, bio, headline, social_links, skills
        FROM users
    """)

    op.drop_column("users", "skills")
    op.drop_column("users", "social_links")
    op.drop_column("users", "headline")
    op.drop_column("users", "bio")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "display_name")
