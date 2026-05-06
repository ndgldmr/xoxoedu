"""Unit tests for AL-BE-2 — program step ordering and enrollment enforcement.

These tests exercise pure logic without a database connection: the enrollment
status transition table, the schema validators, and the ordering invariants
encoded in the service layer.
"""

import uuid

import pytest

from app.core.exceptions import InvalidStatusTransition, ProgramStepConflict
from app.modules.programs.schemas import (
    VALID_ENROLLMENT_TRANSITIONS,
    ProgramEnrollmentUpdateIn,
    ProgramStepReorderIn,
)


# ── Enrollment status transitions ──────────────────────────────────────────────

class TestEnrollmentStatusTransitions:
    """Verify the enrollment lifecycle transition table is correct."""

    def test_active_can_suspend(self) -> None:
        assert "suspended" in VALID_ENROLLMENT_TRANSITIONS["active"]

    def test_active_can_complete(self) -> None:
        assert "completed" in VALID_ENROLLMENT_TRANSITIONS["active"]

    def test_active_can_cancel(self) -> None:
        assert "canceled" in VALID_ENROLLMENT_TRANSITIONS["active"]

    def test_suspended_can_reactivate(self) -> None:
        assert "active" in VALID_ENROLLMENT_TRANSITIONS["suspended"]

    def test_suspended_can_cancel(self) -> None:
        assert "canceled" in VALID_ENROLLMENT_TRANSITIONS["suspended"]

    def test_completed_cannot_reactivate(self) -> None:
        assert "active" not in VALID_ENROLLMENT_TRANSITIONS["completed"]

    def test_completed_can_cancel(self) -> None:
        assert "canceled" in VALID_ENROLLMENT_TRANSITIONS["completed"]

    def test_canceled_allows_no_transitions(self) -> None:
        assert VALID_ENROLLMENT_TRANSITIONS["canceled"] == set()

    def test_all_four_statuses_defined(self) -> None:
        assert set(VALID_ENROLLMENT_TRANSITIONS.keys()) == {
            "active", "suspended", "completed", "canceled"
        }


# ── Enrollment update schema validation ───────────────────────────────────────

class TestProgramEnrollmentUpdateInSchema:
    """Verify the ProgramEnrollmentUpdateIn validator rejects unknown statuses."""

    def test_valid_status_accepted(self) -> None:
        obj = ProgramEnrollmentUpdateIn(status="suspended")
        assert obj.status == "suspended"

    def test_unknown_status_rejected(self) -> None:
        with pytest.raises(Exception):  # pydantic ValidationError
            ProgramEnrollmentUpdateIn(status="gobbledygook")

    @pytest.mark.parametrize("status", ["active", "suspended", "completed", "canceled"])
    def test_all_known_statuses_accepted(self, status: str) -> None:
        obj = ProgramEnrollmentUpdateIn(status=status)
        assert obj.status == status


# ── ProgramStep reorder schema validation ─────────────────────────────────────

class TestProgramStepReorderSchema:
    """Verify the reorder schema rejects empty lists."""

    def test_rejects_empty_list(self) -> None:
        with pytest.raises(Exception):
            ProgramStepReorderIn(step_ids=[])

    def test_accepts_single_item(self) -> None:
        sid = uuid.uuid4()
        obj = ProgramStepReorderIn(step_ids=[sid])
        assert obj.step_ids == [sid]

    def test_accepts_multiple_items(self) -> None:
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        obj = ProgramStepReorderIn(step_ids=ids)
        assert obj.step_ids == ids


# ── Reorder position assignment logic ─────────────────────────────────────────

class TestReorderPositionAssignment:
    """Verify that reorder assigns positions 1..N in step_ids order.

    The service reorder function is async/DB-bound; here we test the
    position assignment logic directly using a lightweight stand-in.
    """

    def _simulate_reorder(
        self, existing: dict[uuid.UUID, int], ordered_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Simulate the two-phase position assignment without a DB."""
        if set(ordered_ids) != set(existing.keys()):
            raise ProgramStepConflict("step_ids must match existing steps exactly")
        result = {}
        for idx, sid in enumerate(ordered_ids):
            result[sid] = idx + 1
        return result

    def test_positions_assigned_one_based(self) -> None:
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        existing = {i: pos + 1 for pos, i in enumerate(ids)}
        reversed_ids = list(reversed(ids))
        positions = self._simulate_reorder(existing, reversed_ids)
        assert positions[reversed_ids[0]] == 1
        assert positions[reversed_ids[1]] == 2
        assert positions[reversed_ids[2]] == 3

    def test_missing_id_raises_conflict(self) -> None:
        ids = [uuid.uuid4(), uuid.uuid4()]
        existing = {ids[0]: 1, ids[1]: 2}
        incomplete = [ids[0]]  # missing ids[1]
        with pytest.raises(ProgramStepConflict):
            self._simulate_reorder(existing, incomplete)

    def test_extra_id_raises_conflict(self) -> None:
        ids = [uuid.uuid4(), uuid.uuid4()]
        existing = {ids[0]: 1, ids[1]: 2}
        extra = ids + [uuid.uuid4()]
        with pytest.raises(ProgramStepConflict):
            self._simulate_reorder(existing, extra)

    def test_single_step_reorder_is_identity(self) -> None:
        sid = uuid.uuid4()
        positions = self._simulate_reorder({sid: 1}, [sid])
        assert positions[sid] == 1
