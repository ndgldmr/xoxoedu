"""Add batches and batch_enrollments tables.

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="upcoming",
        ),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enrollment_opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrollment_closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_batches_course_id", "batches", ["course_id"])
    op.create_index("ix_batches_status", "batches", ["status"])

    op.create_table(
        "batch_enrollments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("enrollment_id", sa.UUID(), nullable=False),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id", "user_id", name="uq_batch_enrollments_batch_user"
        ),
    )
    op.create_index("ix_batch_enrollments_batch_id", "batch_enrollments", ["batch_id"])
    op.create_index("ix_batch_enrollments_user_id", "batch_enrollments", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_batch_enrollments_user_id", table_name="batch_enrollments")
    op.drop_index("ix_batch_enrollments_batch_id", table_name="batch_enrollments")
    op.drop_table("batch_enrollments")
    op.drop_index("ix_batches_status", table_name="batches")
    op.drop_index("ix_batches_course_id", table_name="batches")
    op.drop_table("batches")
