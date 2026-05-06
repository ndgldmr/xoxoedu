"""Unit tests for Sprint 11C — attendance rate helpers and schema validation."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.batches.attendance_schemas import AttendanceIn
from app.modules.batches.attendance_service import _attendance_rate


# ── Attendance rate calculations ───────────────────────────────────────────────

class TestAttendanceRate:
    def test_full_attendance(self) -> None:
        assert _attendance_rate(10, 10) == 1.0

    def test_zero_attendance(self) -> None:
        assert _attendance_rate(0, 10) == 0.0

    def test_partial_attendance(self) -> None:
        assert _attendance_rate(3, 4) == 0.75

    def test_late_counts_as_attended(self) -> None:
        # 2 present + 1 late = 3 attended out of 5
        assert _attendance_rate(3, 5) == 0.6

    def test_zero_total_returns_zero(self) -> None:
        # No divide-by-zero; returns 0.0 when denominator is zero
        assert _attendance_rate(0, 0) == 0.0

    def test_result_rounds_to_four_decimal_places(self) -> None:
        # 1/3 = 0.3333...
        result = _attendance_rate(1, 3)
        assert result == round(1 / 3, 4)

    def test_all_late_full_rate(self) -> None:
        # All late → caller passes (present + late) as attended
        assert _attendance_rate(5, 5) == 1.0

    def test_one_of_many(self) -> None:
        assert _attendance_rate(1, 100) == 0.01


# ── AttendanceIn schema ────────────────────────────────────────────────────────

class TestAttendanceInSchema:
    def test_present_is_valid(self) -> None:
        body = AttendanceIn(status="present")
        assert body.status == "present"

    def test_absent_is_valid(self) -> None:
        body = AttendanceIn(status="absent")
        assert body.status == "absent"

    def test_late_is_valid(self) -> None:
        body = AttendanceIn(status="late")
        assert body.status == "late"

    def test_unknown_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            AttendanceIn(status="skipped")  # type: ignore[arg-type]

    def test_empty_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            AttendanceIn(status="")  # type: ignore[arg-type]

    def test_user_id_defaults_to_none(self) -> None:
        body = AttendanceIn(status="present")
        assert body.user_id is None

    def test_user_id_accepted_when_provided(self) -> None:
        uid = uuid.uuid4()
        body = AttendanceIn(status="late", user_id=uid)
        assert body.user_id == uid

    def test_case_sensitive_status(self) -> None:
        # "Present" with capital P is not a valid Literal value
        with pytest.raises(ValidationError):
            AttendanceIn(status="Present")  # type: ignore[arg-type]


# ── Batch-level rate calculation ───────────────────────────────────────────────

class TestOverallAttendanceRate:
    """Validate overall rate formula: attended / (sessions * members)."""

    def test_perfect_attendance(self) -> None:
        sessions = 5
        members = 10
        # All attended
        total_attended = sessions * members
        rate = _attendance_rate(total_attended, sessions * members)
        assert rate == 1.0

    def test_half_attendance(self) -> None:
        rate = _attendance_rate(10, 20)
        assert rate == 0.5

    def test_no_sessions_returns_zero(self) -> None:
        # 0 sessions × N members = 0 total pairs
        rate = _attendance_rate(0, 0)
        assert rate == 0.0

    def test_no_members_returns_zero(self) -> None:
        rate = _attendance_rate(0, 0)
        assert rate == 0.0
