"""Add grading columns to assignment_submissions; create announcements table

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── assignment_submissions — grading columns ───────────────────────────────
    op.add_column(
        "assignment_submissions",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "assignment_submissions",
        sa.Column("grade_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "assignment_submissions",
        sa.Column("grade_feedback", sa.Text(), nullable=True),
    )
    op.add_column(
        "assignment_submissions",
        sa.Column("grade_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "assignment_submissions",
        sa.Column("graded_by", sa.UUID(), nullable=True),
    )
    op.add_column(
        "assignment_submissions",
        sa.Column(
            "is_reopened", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_foreign_key(
        "fk_assignment_submissions_graded_by",
        "assignment_submissions",
        "users",
        ["graded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_assignment_submissions_graded_by",
        "assignment_submissions",
        ["graded_by"],
    )

    # ── announcements ──────────────────────────────────────────────────────────
    op.create_table(
        "announcements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "scope IN ('course', 'platform')",
            name="ck_announcements_scope",
        ),
    )
    op.create_index("ix_announcements_course_id", "announcements", ["course_id"])
    op.create_index("ix_announcements_created_at", "announcements", ["created_at"])


def downgrade() -> None:
    op.drop_table("announcements")

    op.drop_index("ix_assignment_submissions_graded_by", "assignment_submissions")
    op.drop_constraint(
        "fk_assignment_submissions_graded_by",
        "assignment_submissions",
        type_="foreignkey",
    )
    op.drop_column("assignment_submissions", "is_reopened")
    op.drop_column("assignment_submissions", "graded_by")
    op.drop_column("assignment_submissions", "grade_published_at")
    op.drop_column("assignment_submissions", "grade_feedback")
    op.drop_column("assignment_submissions", "grade_score")
    op.drop_column("assignment_submissions", "attempt_number")
