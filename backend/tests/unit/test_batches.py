"""Unit tests for batch status transition validation and timezone validation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.exceptions import InvalidStatusTransition
from app.db.models.batch import Batch
from app.modules.batches.schemas import (
    VALID_TRANSFER_REQUEST_TRANSITIONS,
    BatchIn,
    BatchSelectionIn,
    BatchTransferRequestIn,
    BatchUpdateIn,
    _validate_iana_timezone,
)
from app.modules.batches.service import (
    _is_batch_open_for_enrollment,
    _remaining_seats,
    validate_status_transition,
    validate_transfer_request_transition,
)

# ── Status transition tests ────────────────────────────────────────────────────

class TestValidateStatusTransition:
    def test_upcoming_to_active_is_allowed(self) -> None:
        validate_status_transition("upcoming", "active")  # no raise

    def test_upcoming_to_archived_is_allowed(self) -> None:
        validate_status_transition("upcoming", "archived")  # no raise

    def test_active_to_archived_is_allowed(self) -> None:
        validate_status_transition("active", "archived")  # no raise

    def test_active_to_upcoming_is_rejected(self) -> None:
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("active", "upcoming")

    def test_archived_to_active_is_rejected(self) -> None:
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("archived", "active")

    def test_archived_to_upcoming_is_rejected(self) -> None:
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("archived", "upcoming")

    def test_archived_to_archived_is_rejected(self) -> None:
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("archived", "archived")

    def test_upcoming_to_upcoming_is_rejected(self) -> None:
        with pytest.raises(InvalidStatusTransition):
            validate_status_transition("upcoming", "upcoming")


# ── Timezone validation tests ──────────────────────────────────────────────────

class TestValidateIanaTimezone:
    def test_valid_us_eastern(self) -> None:
        assert _validate_iana_timezone("America/New_York") == "America/New_York"

    def test_valid_utc(self) -> None:
        assert _validate_iana_timezone("UTC") == "UTC"

    def test_valid_london(self) -> None:
        assert _validate_iana_timezone("Europe/London") == "Europe/London"

    def test_invalid_timezone_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid IANA timezone"):
            _validate_iana_timezone("Not/A/Timezone")

    def test_completely_made_up_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid IANA timezone"):
            _validate_iana_timezone("FOOBAR/InvalidZone")


# ── BatchIn schema validation ──────────────────────────────────────────────────

class TestBatchInSchema:
    def _base_data(self) -> dict:
        return {
            "program_id": "00000000-0000-0000-0000-000000000001",
            "title": "Spring 2026",
            "timezone": "UTC",
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2026-04-01T00:00:00Z",
        }

    def test_valid_batch_passes(self) -> None:
        BatchIn(**self._base_data())  # no raise

    def test_ends_before_starts_raises(self) -> None:
        data = self._base_data()
        data["starts_at"] = "2026-04-01T00:00:00Z"
        data["ends_at"] = "2026-01-01T00:00:00Z"
        with pytest.raises(ValueError, match="ends_at must be after starts_at"):
            BatchIn(**data)

    def test_ends_equal_starts_raises(self) -> None:
        data = self._base_data()
        data["ends_at"] = data["starts_at"]
        with pytest.raises(ValueError, match="ends_at must be after starts_at"):
            BatchIn(**data)

    def test_invalid_timezone_raises(self) -> None:
        data = self._base_data()
        data["timezone"] = "Fake/Zone"
        with pytest.raises(ValueError, match="not a valid IANA timezone"):
            BatchIn(**data)

    def test_capacity_must_be_positive(self) -> None:
        data = self._base_data()
        data["capacity"] = 0
        with pytest.raises(ValueError):
            BatchIn(**data)

    def test_optional_fields_default_to_none(self) -> None:
        b = BatchIn(**self._base_data())
        assert b.enrollment_opens_at is None
        assert b.enrollment_closes_at is None
        assert b.capacity is None


# ── BatchUpdateIn schema validation ───────────────────────────────────────────

class TestBatchUpdateInSchema:
    def test_empty_update_is_valid(self) -> None:
        BatchUpdateIn()  # no raise

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError):
            BatchUpdateIn(status="published")

    def test_valid_statuses_are_accepted(self) -> None:
        for s in ("upcoming", "active", "archived"):
            BatchUpdateIn(status=s)  # no raise

    def test_invalid_timezone_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid IANA timezone"):
            BatchUpdateIn(timezone="Bad/Zone")


class TestBatchSelectionInSchema:
    def test_requires_batch_id(self) -> None:
        with pytest.raises(ValidationError):
            BatchSelectionIn()

    def test_accepts_uuid(self) -> None:
        batch_id = uuid.uuid4()
        obj = BatchSelectionIn(batch_id=batch_id)
        assert obj.batch_id == batch_id


class TestBatchTransferRequestInSchema:
    def test_requires_to_batch_id(self) -> None:
        with pytest.raises(ValidationError):
            BatchTransferRequestIn()

    def test_accepts_uuid_and_reason(self) -> None:
        batch_id = uuid.uuid4()
        obj = BatchTransferRequestIn(to_batch_id=batch_id, reason="Need a later schedule")
        assert obj.to_batch_id == batch_id
        assert obj.reason == "Need a later schedule"


class TestValidateTransferRequestTransition:
    def test_pending_to_approved_is_allowed(self) -> None:
        validate_transfer_request_transition("pending", "approved")

    def test_pending_to_denied_is_allowed(self) -> None:
        validate_transfer_request_transition("pending", "denied")

    def test_approved_to_denied_is_rejected(self) -> None:
        with pytest.raises(InvalidStatusTransition):
            validate_transfer_request_transition("approved", "denied")

    def test_denied_to_approved_is_rejected(self) -> None:
        with pytest.raises(InvalidStatusTransition):
            validate_transfer_request_transition("denied", "approved")

    def test_transition_map_covers_expected_states(self) -> None:
        assert set(VALID_TRANSFER_REQUEST_TRANSITIONS.keys()) == {
            "pending",
            "approved",
            "denied",
            "canceled",
        }


class TestBatchAvailabilityHelpers:
    def _make_batch(self, **overrides: object) -> Batch:
        now = datetime.now(UTC)
        data = {
            "id": uuid.uuid4(),
            "program_id": uuid.uuid4(),
            "title": "Spring Cohort",
            "status": "upcoming",
            "timezone": "UTC",
            "starts_at": now + timedelta(days=7),
            "ends_at": now + timedelta(days=90),
            "enrollment_opens_at": now - timedelta(days=1),
            "enrollment_closes_at": now + timedelta(days=7),
            "capacity": 15,
        }
        data.update(overrides)
        return Batch(**data)

    def test_open_batch_is_selectable(self) -> None:
        batch = self._make_batch()
        assert _is_batch_open_for_enrollment(batch, now=datetime.now(UTC)) is True

    def test_archived_batch_is_not_selectable(self) -> None:
        batch = self._make_batch(status="archived")
        assert _is_batch_open_for_enrollment(batch, now=datetime.now(UTC)) is False

    def test_batch_not_yet_open_is_not_selectable(self) -> None:
        now = datetime.now(UTC)
        batch = self._make_batch(enrollment_opens_at=now + timedelta(hours=1))
        assert _is_batch_open_for_enrollment(batch, now=now) is False

    def test_batch_after_close_is_not_selectable(self) -> None:
        now = datetime.now(UTC)
        batch = self._make_batch(enrollment_closes_at=now - timedelta(seconds=1))
        assert _is_batch_open_for_enrollment(batch, now=now) is False

    def test_remaining_seats_never_goes_negative(self) -> None:
        batch = self._make_batch(capacity=2)
        assert _remaining_seats(batch, 5) == 0

    def test_remaining_seats_returns_capacity_delta(self) -> None:
        batch = self._make_batch(capacity=15)
        assert _remaining_seats(batch, 4) == 11
