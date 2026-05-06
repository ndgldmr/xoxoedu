"""Unit tests for AL-BE-1 — new domain model ORM structure.

These tests verify the ORM model definitions in-memory without a database
connection.  They check column declarations, constraint names, relationship
names, and default values that must be present for the aligned schema to work
correctly.
"""

import app.db.models  # noqa: F401 — register all models so metadata is populated
from app.db.base import Base
from app.db.models.batch import Batch, BatchEnrollment, BatchTransferRequest
from app.db.models.placement import PlacementAttempt, PlacementResult
from app.db.models.program import Program, ProgramEnrollment, ProgramStep
from app.db.models.subscription import (
    BillingCycle,
    PaymentTransaction,
    Subscription,
    SubscriptionPlan,
)
from app.db.models.user import User


# ── Program model ──────────────────────────────────────────────────────────────


class TestProgramModel:
    def test_table_name(self) -> None:
        assert Program.__tablename__ == "programs"

    def test_code_column_exists(self) -> None:
        col = Program.__table__.c["code"]
        assert col is not None
        assert col.unique

    def test_is_active_defaults_true(self) -> None:
        col = Program.__table__.c["is_active"]
        assert col.default.arg is True


class TestProgramStepModel:
    def test_table_name(self) -> None:
        assert ProgramStep.__tablename__ == "program_steps"

    def test_program_course_unique_constraint_exists(self) -> None:
        constraint_names = {
            c.name for c in ProgramStep.__table__.constraints
        }
        assert "uq_program_steps_program_course" in constraint_names

    def test_program_position_unique_constraint_exists(self) -> None:
        constraint_names = {
            c.name for c in ProgramStep.__table__.constraints
        }
        assert "uq_program_steps_program_position" in constraint_names

    def test_is_required_defaults_true(self) -> None:
        col = ProgramStep.__table__.c["is_required"]
        assert col.default.arg is True


class TestProgramEnrollmentModel:
    def test_table_name(self) -> None:
        assert ProgramEnrollment.__tablename__ == "program_enrollments"

    def test_user_program_unique_constraint_exists(self) -> None:
        constraint_names = {
            c.name for c in ProgramEnrollment.__table__.constraints
        }
        assert "uq_program_enrollments_user_program" in constraint_names

    def test_status_defaults_active(self) -> None:
        col = ProgramEnrollment.__table__.c["status"]
        assert col.default.arg == "active"

    def test_completed_at_nullable(self) -> None:
        col = ProgramEnrollment.__table__.c["completed_at"]
        assert col.nullable


# ── Batch model (re-scoped) ────────────────────────────────────────────────────


class TestBatchModel:
    def test_program_id_column_exists(self) -> None:
        assert "program_id" in Batch.__table__.c

    def test_course_id_column_removed(self) -> None:
        assert "course_id" not in Batch.__table__.c

    def test_capacity_defaults_15(self) -> None:
        col = Batch.__table__.c["capacity"]
        assert col.default.arg == 15


class TestBatchEnrollmentModel:
    def test_program_enrollment_id_column_exists(self) -> None:
        assert "program_enrollment_id" in BatchEnrollment.__table__.c

    def test_enrollment_id_column_removed(self) -> None:
        assert "enrollment_id" not in BatchEnrollment.__table__.c

    def test_batch_user_unique_constraint_preserved(self) -> None:
        constraint_names = {
            c.name for c in BatchEnrollment.__table__.constraints
        }
        assert "uq_batch_enrollments_batch_user" in constraint_names


class TestBatchTransferRequestModel:
    def test_table_name(self) -> None:
        assert BatchTransferRequest.__tablename__ == "batch_transfer_requests"

    def test_status_defaults_pending(self) -> None:
        col = BatchTransferRequest.__table__.c["status"]
        assert col.default.arg == "pending"

    def test_from_to_batch_nullable(self) -> None:
        assert BatchTransferRequest.__table__.c["from_batch_id"].nullable
        assert BatchTransferRequest.__table__.c["to_batch_id"].nullable

    def test_reason_nullable(self) -> None:
        assert BatchTransferRequest.__table__.c["reason"].nullable

    def test_reviewed_by_nullable(self) -> None:
        assert BatchTransferRequest.__table__.c["reviewed_by"].nullable


# ── Subscription models ────────────────────────────────────────────────────────


class TestSubscriptionPlanModel:
    def test_table_name(self) -> None:
        assert SubscriptionPlan.__tablename__ == "subscription_plans"

    def test_interval_defaults_month(self) -> None:
        col = SubscriptionPlan.__table__.c["interval"]
        assert col.default.arg == "month"

    def test_is_active_defaults_true(self) -> None:
        col = SubscriptionPlan.__table__.c["is_active"]
        assert col.default.arg is True


class TestSubscriptionModel:
    def test_table_name(self) -> None:
        assert Subscription.__tablename__ == "subscriptions"

    def test_plan_id_nullable(self) -> None:
        assert Subscription.__table__.c["plan_id"].nullable

    def test_provider_subscription_id_unique(self) -> None:
        assert Subscription.__table__.c["provider_subscription_id"].unique

    def test_status_defaults_active(self) -> None:
        col = Subscription.__table__.c["status"]
        assert col.default.arg == "active"


class TestBillingCycleModel:
    def test_table_name(self) -> None:
        assert BillingCycle.__tablename__ == "billing_cycles"

    def test_status_defaults_pending(self) -> None:
        col = BillingCycle.__table__.c["status"]
        assert col.default.arg == "pending"

    def test_paid_at_nullable(self) -> None:
        assert BillingCycle.__table__.c["paid_at"].nullable

    def test_reminder_sent_at_nullable(self) -> None:
        assert BillingCycle.__table__.c["reminder_sent_at"].nullable


class TestPaymentTransactionModel:
    def test_table_name(self) -> None:
        assert PaymentTransaction.__tablename__ == "payment_transactions"

    def test_no_updated_at_column(self) -> None:
        assert "updated_at" not in PaymentTransaction.__table__.c

    def test_has_created_at_column(self) -> None:
        assert "created_at" in PaymentTransaction.__table__.c

    def test_subscription_id_nullable(self) -> None:
        assert PaymentTransaction.__table__.c["subscription_id"].nullable

    def test_billing_cycle_id_nullable(self) -> None:
        assert PaymentTransaction.__table__.c["billing_cycle_id"].nullable

    def test_provider_transaction_id_unique(self) -> None:
        assert PaymentTransaction.__table__.c["provider_transaction_id"].unique


# ── Placement models ───────────────────────────────────────────────────────────


class TestPlacementAttemptModel:
    def test_table_name(self) -> None:
        assert PlacementAttempt.__tablename__ == "placement_attempts"

    def test_score_nullable(self) -> None:
        assert PlacementAttempt.__table__.c["score"].nullable

    def test_completed_at_nullable(self) -> None:
        assert PlacementAttempt.__table__.c["completed_at"].nullable

    def test_meta_nullable(self) -> None:
        assert PlacementAttempt.__table__.c["meta"].nullable


class TestPlacementResultModel:
    def test_table_name(self) -> None:
        assert PlacementResult.__tablename__ == "placement_results"

    def test_attempt_id_nullable(self) -> None:
        assert PlacementResult.__table__.c["attempt_id"].nullable

    def test_program_id_nullable(self) -> None:
        assert PlacementResult.__table__.c["program_id"].nullable

    def test_is_override_defaults_false(self) -> None:
        col = PlacementResult.__table__.c["is_override"]
        assert col.default.arg is False


# ── User model extensions ──────────────────────────────────────────────────────


class TestUserModelExtensions:
    def test_date_of_birth_column_exists(self) -> None:
        assert "date_of_birth" in User.__table__.c

    def test_date_of_birth_nullable(self) -> None:
        assert User.__table__.c["date_of_birth"].nullable

    def test_country_column_exists(self) -> None:
        assert "country" in User.__table__.c

    def test_country_max_length_2(self) -> None:
        col = User.__table__.c["country"]
        assert col.type.length == 2

    def test_gender_column_exists(self) -> None:
        assert "gender" in User.__table__.c

    def test_gender_self_describe_column_exists(self) -> None:
        assert "gender_self_describe" in User.__table__.c

    def test_gender_self_describe_nullable(self) -> None:
        assert User.__table__.c["gender_self_describe"].nullable


# ── Base metadata completeness ─────────────────────────────────────────────────


class TestBaseMetadata:
    """Verify all new tables are registered in Base.metadata."""

    def test_programs_table_registered(self) -> None:
        assert "programs" in Base.metadata.tables

    def test_program_steps_table_registered(self) -> None:
        assert "program_steps" in Base.metadata.tables

    def test_program_enrollments_table_registered(self) -> None:
        assert "program_enrollments" in Base.metadata.tables

    def test_subscription_plans_table_registered(self) -> None:
        assert "subscription_plans" in Base.metadata.tables

    def test_subscriptions_table_registered(self) -> None:
        assert "subscriptions" in Base.metadata.tables

    def test_billing_cycles_table_registered(self) -> None:
        assert "billing_cycles" in Base.metadata.tables

    def test_payment_transactions_table_registered(self) -> None:
        assert "payment_transactions" in Base.metadata.tables

    def test_placement_attempts_table_registered(self) -> None:
        assert "placement_attempts" in Base.metadata.tables

    def test_placement_results_table_registered(self) -> None:
        assert "placement_results" in Base.metadata.tables

    def test_batch_transfer_requests_table_registered(self) -> None:
        assert "batch_transfer_requests" in Base.metadata.tables
