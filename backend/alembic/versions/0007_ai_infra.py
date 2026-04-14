"""Create ai_usage_logs and ai_usage_budgets tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── ai_usage_logs ──────────────────────────────────────────────────────────
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("course_id", sa.UUID(), nullable=True),
        sa.Column("feature", sa.String(50), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_logs_user_id", "ai_usage_logs", ["user_id"])
    op.create_index("ix_ai_usage_logs_course_id", "ai_usage_logs", ["course_id"])

    # ── ai_usage_budgets ───────────────────────────────────────────────────────
    op.create_table(
        "ai_usage_budgets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("tone", sa.String(20), nullable=False, server_default="encouraging"),
        sa.Column("system_prompt_override", sa.Text(), nullable=True),
        sa.Column(
            "monthly_token_limit", sa.Integer(), nullable=False, server_default="100000"
        ),
        sa.Column(
            "alert_threshold", sa.Float(), nullable=False, server_default="0.8"
        ),
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
            ["course_id"], ["courses.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", name="uq_ai_usage_budgets_course_id"),
    )
    op.create_index(
        "ix_ai_usage_budgets_course_id", "ai_usage_budgets", ["course_id"]
    )


def downgrade() -> None:
    op.drop_table("ai_usage_budgets")
    op.drop_table("ai_usage_logs")
