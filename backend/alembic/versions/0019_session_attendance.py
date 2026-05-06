"""Add session_attendance table.

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_attendance",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["session_id"], ["live_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "user_id", name="uq_session_attendance_session_user"
        ),
    )
    op.create_index(
        "ix_session_attendance_session_id", "session_attendance", ["session_id"]
    )
    op.create_index(
        "ix_session_attendance_user_id", "session_attendance", ["user_id"]
    )
    op.create_index(
        "ix_session_attendance_status", "session_attendance", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_session_attendance_status", table_name="session_attendance")
    op.drop_index("ix_session_attendance_user_id", table_name="session_attendance")
    op.drop_index(
        "ix_session_attendance_session_id", table_name="session_attendance"
    )
    op.drop_table("session_attendance")
