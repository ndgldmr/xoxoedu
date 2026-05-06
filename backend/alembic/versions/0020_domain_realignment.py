"""AL-BE-1: Domain Reset and Schema Realignment.

Establishes the canonical aligned domain model for XOXO Education:
- Adds programs, program_steps, program_enrollments
- Adds subscription_plans, subscriptions, billing_cycles, payment_transactions
- Adds placement_attempts, placement_results
- Adds batch_transfer_requests
- Re-scopes batches from course_id to program_id
- Updates batch_enrollments to reference program_enrollment_id instead of enrollment_id
- Extends users with date_of_birth, country, gender, gender_self_describe

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── users: extend with onboarding profile fields ───────────────────────────
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("country", sa.String(2), nullable=True))
    op.add_column("users", sa.Column("gender", sa.String(30), nullable=True))
    op.add_column("users", sa.Column("gender_self_describe", sa.String(255), nullable=True))

    # ── programs ───────────────────────────────────────────────────────────────
    op.create_table(
        "programs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_programs_code"),
    )
    op.create_index("ix_programs_code", "programs", ["code"])

    # ── program_steps ──────────────────────────────────────────────────────────
    op.create_table(
        "program_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("program_id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "course_id", name="uq_program_steps_program_course"),
        sa.UniqueConstraint("program_id", "position", name="uq_program_steps_program_position"),
    )
    op.create_index("ix_program_steps_program_id", "program_steps", ["program_id"])
    op.create_index("ix_program_steps_course_id", "program_steps", ["course_id"])

    # ── program_enrollments ────────────────────────────────────────────────────
    op.create_table(
        "program_enrollments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("program_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "program_id", name="uq_program_enrollments_user_program"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'suspended', 'canceled')",
            name="ck_program_enrollments_status",
        ),
    )
    op.create_index("ix_program_enrollments_user_id", "program_enrollments", ["user_id"])
    op.create_index("ix_program_enrollments_program_id", "program_enrollments", ["program_id"])
    op.create_index("ix_program_enrollments_status", "program_enrollments", ["status"])

    # ── batch_enrollments: replace enrollment_id with program_enrollment_id ───
    op.drop_constraint(
        "batch_enrollments_enrollment_id_fkey",
        "batch_enrollments",
        type_="foreignkey",
    )
    op.drop_column("batch_enrollments", "enrollment_id")
    op.add_column(
        "batch_enrollments",
        sa.Column("program_enrollment_id", sa.UUID(), nullable=False),
    )
    op.create_foreign_key(
        "batch_enrollments_program_enrollment_id_fkey",
        "batch_enrollments",
        "program_enrollments",
        ["program_enrollment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_batch_enrollments_program_enrollment_id",
        "batch_enrollments",
        ["program_enrollment_id"],
    )

    # ── batches: swap course_id → program_id, set default capacity ────────────
    op.drop_index("ix_batches_course_id", table_name="batches")
    op.drop_constraint("batches_course_id_fkey", "batches", type_="foreignkey")
    op.drop_column("batches", "course_id")
    op.add_column("batches", sa.Column("program_id", sa.UUID(), nullable=False))
    op.create_foreign_key(
        "batches_program_id_fkey",
        "batches",
        "programs",
        ["program_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_batches_program_id", "batches", ["program_id"])
    # Backfill any NULL capacity rows before tightening the constraint.
    # Current data is fake/disposable; 15 is the launch cohort limit.
    op.execute("UPDATE batches SET capacity = 15 WHERE capacity IS NULL")
    op.alter_column(
        "batches",
        "capacity",
        nullable=False,
        server_default="15",
    )

    # ── batch_transfer_requests ────────────────────────────────────────────────
    op.create_table(
        "batch_transfer_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("from_batch_id", sa.UUID(), nullable=True),
        sa.Column("to_batch_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["from_batch_id"], ["batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_batch_id"], ["batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'denied', 'canceled')",
            name="ck_batch_transfer_requests_status",
        ),
    )
    op.create_index("ix_batch_transfer_requests_user_id", "batch_transfer_requests", ["user_id"])
    op.create_index(
        "ix_batch_transfer_requests_from_batch_id",
        "batch_transfer_requests",
        ["from_batch_id"],
    )
    op.create_index(
        "ix_batch_transfer_requests_to_batch_id",
        "batch_transfer_requests",
        ["to_batch_id"],
    )
    op.create_index(
        "ix_batch_transfer_requests_status", "batch_transfer_requests", ["status"]
    )

    # ── subscription_plans ─────────────────────────────────────────────────────
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("market", sa.String(10), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("interval", sa.String(20), nullable=False, server_default="month"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_plans_market", "subscription_plans", ["market"])

    # ── subscriptions ──────────────────────────────────────────────────────────
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=True),
        sa.Column("market", sa.String(10), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("provider_subscription_id", sa.String(255), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["plan_id"], ["subscription_plans.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_subscription_id", name="uq_subscriptions_provider_subscription_id"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'past_due', 'canceled', 'trialing')",
            name="ck_subscriptions_status",
        ),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])

    # ── billing_cycles ─────────────────────────────────────────────────────────
    op.create_table(
        "billing_cycles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_invoice_id", sa.String(255), nullable=True),
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
            ["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'waived')",
            name="ck_billing_cycles_status",
        ),
    )
    op.create_index("ix_billing_cycles_subscription_id", "billing_cycles", ["subscription_id"])
    op.create_index("ix_billing_cycles_status", "billing_cycles", ["status"])

    # ── payment_transactions ───────────────────────────────────────────────────
    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("billing_cycle_id", sa.UUID(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("provider_transaction_id", sa.String(255), nullable=True),
        sa.Column("provider_payload", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["billing_cycle_id"], ["billing_cycles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_transaction_id",
            name="uq_payment_transactions_provider_transaction_id",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'refunded', 'pending')",
            name="ck_payment_transactions_status",
        ),
    )
    op.create_index("ix_payment_transactions_user_id", "payment_transactions", ["user_id"])
    op.create_index(
        "ix_payment_transactions_subscription_id",
        "payment_transactions",
        ["subscription_id"],
    )
    op.create_index(
        "ix_payment_transactions_billing_cycle_id",
        "payment_transactions",
        ["billing_cycle_id"],
    )

    # ── placement_attempts ─────────────────────────────────────────────────────
    op.create_table(
        "placement_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("answers", JSONB, nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSONB, nullable=True),
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
    )
    op.create_index("ix_placement_attempts_user_id", "placement_attempts", ["user_id"])

    # ── placement_results ──────────────────────────────────────────────────────
    op.create_table(
        "placement_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("program_id", sa.UUID(), nullable=True),
        sa.Column("level", sa.String(50), nullable=True),
        sa.Column("is_override", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
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
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["placement_attempts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_placement_results_user_id", "placement_results", ["user_id"])
    op.create_index("ix_placement_results_attempt_id", "placement_results", ["attempt_id"])
    op.create_index("ix_placement_results_program_id", "placement_results", ["program_id"])


def downgrade() -> None:
    # Drop in reverse dependency order

    # placement_results, placement_attempts
    op.drop_index("ix_placement_results_program_id", table_name="placement_results")
    op.drop_index("ix_placement_results_attempt_id", table_name="placement_results")
    op.drop_index("ix_placement_results_user_id", table_name="placement_results")
    op.drop_table("placement_results")

    op.drop_index("ix_placement_attempts_user_id", table_name="placement_attempts")
    op.drop_table("placement_attempts")

    # payment_transactions
    op.drop_index(
        "ix_payment_transactions_billing_cycle_id", table_name="payment_transactions"
    )
    op.drop_index(
        "ix_payment_transactions_subscription_id", table_name="payment_transactions"
    )
    op.drop_index("ix_payment_transactions_user_id", table_name="payment_transactions")
    op.drop_table("payment_transactions")

    # billing_cycles
    op.drop_index("ix_billing_cycles_status", table_name="billing_cycles")
    op.drop_index("ix_billing_cycles_subscription_id", table_name="billing_cycles")
    op.drop_table("billing_cycles")

    # subscriptions
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    # subscription_plans
    op.drop_index("ix_subscription_plans_market", table_name="subscription_plans")
    op.drop_table("subscription_plans")

    # batch_transfer_requests
    op.drop_index(
        "ix_batch_transfer_requests_status", table_name="batch_transfer_requests"
    )
    op.drop_index(
        "ix_batch_transfer_requests_to_batch_id", table_name="batch_transfer_requests"
    )
    op.drop_index(
        "ix_batch_transfer_requests_from_batch_id", table_name="batch_transfer_requests"
    )
    op.drop_index(
        "ix_batch_transfer_requests_user_id", table_name="batch_transfer_requests"
    )
    op.drop_table("batch_transfer_requests")

    # batches: restore course_id
    op.drop_index("ix_batches_program_id", table_name="batches")
    op.drop_constraint("batches_program_id_fkey", "batches", type_="foreignkey")
    op.drop_column("batches", "program_id")
    op.add_column("batches", sa.Column("course_id", sa.UUID(), nullable=False))
    op.create_foreign_key(
        "batches_course_id_fkey",
        "batches",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_batches_course_id", "batches", ["course_id"])
    op.alter_column("batches", "capacity", nullable=True, server_default=None)

    # batch_enrollments: restore enrollment_id
    op.drop_index(
        "ix_batch_enrollments_program_enrollment_id", table_name="batch_enrollments"
    )
    op.drop_constraint(
        "batch_enrollments_program_enrollment_id_fkey",
        "batch_enrollments",
        type_="foreignkey",
    )
    op.drop_column("batch_enrollments", "program_enrollment_id")
    op.add_column(
        "batch_enrollments", sa.Column("enrollment_id", sa.UUID(), nullable=False)
    )
    op.create_foreign_key(
        "batch_enrollments_enrollment_id_fkey",
        "batch_enrollments",
        "enrollments",
        ["enrollment_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # program_enrollments
    op.drop_index("ix_program_enrollments_status", table_name="program_enrollments")
    op.drop_index("ix_program_enrollments_program_id", table_name="program_enrollments")
    op.drop_index("ix_program_enrollments_user_id", table_name="program_enrollments")
    op.drop_table("program_enrollments")

    # program_steps
    op.drop_index("ix_program_steps_course_id", table_name="program_steps")
    op.drop_index("ix_program_steps_program_id", table_name="program_steps")
    op.drop_table("program_steps")

    # programs
    op.drop_index("ix_programs_code", table_name="programs")
    op.drop_table("programs")

    # users: remove onboarding fields
    op.drop_column("users", "gender_self_describe")
    op.drop_column("users", "gender")
    op.drop_column("users", "country")
    op.drop_column("users", "date_of_birth")
