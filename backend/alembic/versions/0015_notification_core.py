"""Add usernames plus notification and notification preference tables.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── users.username ────────────────────────────────────────────────────────
    op.add_column("users", sa.Column("username", sa.String(length=50), nullable=True))
    op.execute(
        """
        UPDATE users
        SET username = LEFT(
            CONCAT(
                COALESCE(
                    NULLIF(
                        TRIM(BOTH '_' FROM REGEXP_REPLACE(
                            LOWER(COALESCE(NULLIF(display_name, ''), SPLIT_PART(email, '@', 1))),
                            '[^a-z0-9_]+',
                            '_',
                            'g'
                        )),
                        ''
                    ),
                    'user'
                ),
                '_',
                SUBSTRING(REPLACE(id::text, '-', '') FROM 1 FOR 8)
            ),
            50
        )
        WHERE username IS NULL
        """
    )
    op.alter_column("users", "username", nullable=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    # ── notifications ────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("actor_summary", sa.String(length=255), nullable=False),
        sa.Column("target_url", sa.String(length=500), nullable=False),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_recipient_read_at",
        "notifications",
        ["recipient_id", "read_at"],
    )
    op.create_index(
        "ix_notifications_recipient_created_id",
        "notifications",
        ["recipient_id", "created_at", "id"],
    )

    # ── notification_prefs ───────────────────────────────────────────────────
    op.create_table(
        "notification_prefs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("notification_type", sa.String(length=50), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "notification_type", name="uq_notification_prefs_user_type"),
    )


def downgrade() -> None:
    op.drop_table("notification_prefs")

    op.drop_index("ix_notifications_recipient_created_id", table_name="notifications")
    op.drop_index("ix_notifications_recipient_read_at", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_column("users", "username")
