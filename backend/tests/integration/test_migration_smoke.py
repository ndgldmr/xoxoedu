"""Integration smoke tests for AL-BE-1 — migration and schema completeness.

These tests verify that the aligned domain schema is present and correct in
the test database.  They use SQLAlchemy Inspector to introspect the actual
table structures rather than relying solely on ORM metadata.

The test database is set up once per session via the ``setup_database`` fixture
in ``tests/integration/conftest.py`` using ``Base.metadata.create_all()``.
These smoke tests verify the ORM-created structure matches what the Alembic
migration would also produce.
"""

import os

import pytest
from sqlalchemy import create_engine, inspect, text

TEST_DATABASE_URL_SYNC = os.environ["DATABASE_URL_SYNC"]

# Tables and required columns introduced in AL-BE-1
_EXPECTED_NEW_TABLES: dict[str, list[str]] = {
    "programs": [
        "id",
        "code",
        "title",
        "description",
        "marketing_summary",
        "cover_image_url",
        "display_order",
        "is_active",
        "created_at",
        "updated_at",
    ],
    "program_steps": ["id", "program_id", "course_id", "position", "is_required"],
    "program_enrollments": [
        "id", "user_id", "program_id", "status", "enrolled_at", "completed_at",
    ],
    "subscription_plans": [
        "id", "name", "market", "currency", "amount_cents", "interval", "is_active",
    ],
    "subscriptions": [
        "id", "user_id", "plan_id", "market", "currency", "amount_cents", "status",
        "provider", "provider_subscription_id", "current_period_start",
        "current_period_end", "canceled_at",
    ],
    "billing_cycles": [
        "id", "subscription_id", "due_date", "paid_at", "amount_cents", "currency",
        "status", "reminder_sent_at", "provider_invoice_id",
    ],
    "payment_transactions": [
        "id", "user_id", "subscription_id", "billing_cycle_id", "amount_cents",
        "currency", "status", "provider", "provider_transaction_id", "provider_payload",
        "created_at",
    ],
    "placement_attempts": [
        "id", "user_id", "answers", "score", "started_at", "completed_at", "meta",
    ],
    "placement_results": [
        "id", "user_id", "attempt_id", "program_id", "level", "is_override", "assigned_at",
    ],
    "batch_transfer_requests": [
        "id", "user_id", "from_batch_id", "to_batch_id", "status", "reason",
        "reviewed_by", "reviewed_at",
    ],
}

# Columns that must now exist on legacy tables after AL-BE-1 modifications
_EXPECTED_MODIFIED_COLUMNS: dict[str, list[str]] = {
    "users": ["date_of_birth", "country", "gender", "gender_self_describe"],
    "batches": ["program_id"],
    "batch_enrollments": ["program_enrollment_id"],
}

# Columns that must NOT exist on tables that were re-scoped
_REMOVED_COLUMNS: dict[str, list[str]] = {
    "batches": ["course_id"],
    "batch_enrollments": ["enrollment_id"],
}

# Preserved content/academic tables that must still be intact
_PRESERVED_TABLES: list[str] = [
    "courses",
    "chapters",
    "lessons",
    "lesson_progress",
    "live_sessions",
    "session_attendance",
]


@pytest.fixture(scope="module")
def inspector():
    """Sync engine inspector scoped to this test module."""
    engine = create_engine(TEST_DATABASE_URL_SYNC)
    insp = inspect(engine)
    yield insp
    engine.dispose()


class TestNewTablesExist:
    @pytest.mark.parametrize("table_name", list(_EXPECTED_NEW_TABLES))
    def test_table_exists(self, inspector, table_name: str) -> None:
        assert inspector.has_table(table_name), f"Table '{table_name}' not found in database"

    @pytest.mark.parametrize("table_name,columns", list(_EXPECTED_NEW_TABLES.items()))
    def test_table_has_expected_columns(
        self, inspector, table_name: str, columns: list[str]
    ) -> None:
        actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
        missing = set(columns) - actual_columns
        assert not missing, (
            f"Table '{table_name}' is missing columns: {missing}"
        )


class TestModifiedTablesUpdated:
    @pytest.mark.parametrize("table_name,columns", list(_EXPECTED_MODIFIED_COLUMNS.items()))
    def test_new_columns_present(
        self, inspector, table_name: str, columns: list[str]
    ) -> None:
        actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
        missing = set(columns) - actual_columns
        assert not missing, (
            f"Table '{table_name}' is missing expected new columns: {missing}"
        )

    @pytest.mark.parametrize("table_name,columns", list(_REMOVED_COLUMNS.items()))
    def test_old_columns_removed(
        self, inspector, table_name: str, columns: list[str]
    ) -> None:
        actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
        still_present = set(columns) & actual_columns
        assert not still_present, (
            f"Table '{table_name}' still has columns that should be removed: {still_present}"
        )


class TestPreservedTablesIntact:
    @pytest.mark.parametrize("table_name", _PRESERVED_TABLES)
    def test_preserved_table_exists(self, inspector, table_name: str) -> None:
        assert inspector.has_table(table_name), (
            f"Preserved table '{table_name}' is missing after AL-BE-1 migration"
        )

    def test_courses_has_core_columns(self, inspector) -> None:
        actual = {col["name"] for col in inspector.get_columns("courses")}
        assert {"id", "slug", "title", "status"}.issubset(actual)

    def test_lessons_has_core_columns(self, inspector) -> None:
        actual = {col["name"] for col in inspector.get_columns("lessons")}
        assert {"id", "chapter_id", "title", "position"}.issubset(actual)

    def test_lesson_progress_has_core_columns(self, inspector) -> None:
        actual = {col["name"] for col in inspector.get_columns("lesson_progress")}
        assert {"id", "user_id", "lesson_id", "status"}.issubset(actual)


class TestBatchCapacityDefault:
    def test_batches_capacity_not_nullable(self, inspector) -> None:
        cols = {col["name"]: col for col in inspector.get_columns("batches")}
        assert "capacity" in cols
        assert not cols["capacity"]["nullable"], "batches.capacity must be NOT NULL"

    def test_batches_capacity_default_is_15(self, inspector) -> None:
        cols = {col["name"]: col for col in inspector.get_columns("batches")}
        default = cols["capacity"].get("default")
        # server_default may be returned as string "15" or integer 15
        assert str(default) == "15", f"Expected server_default=15, got {default!r}"


class TestPaymentTransactionNoUpdatedAt:
    def test_no_updated_at_column(self, inspector) -> None:
        actual = {col["name"] for col in inspector.get_columns("payment_transactions")}
        assert "updated_at" not in actual, (
            "payment_transactions must not have updated_at — it is an append-only log"
        )
