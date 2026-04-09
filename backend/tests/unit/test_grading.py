"""Unit tests for grading schema validation logic."""

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.admin.schemas import GradeSubmissionIn


def test_grade_submission_in_defaults_to_draft() -> None:
    """GradeSubmissionIn.publish defaults to False (draft mode)."""
    data = GradeSubmissionIn(grade_score=85.0, grade_feedback="Good work.")
    assert data.publish is False


def test_grade_submission_in_publish_true() -> None:
    """GradeSubmissionIn can be set to publish=True."""
    data = GradeSubmissionIn(grade_score=72.5, grade_feedback="Needs improvement.", publish=True)
    assert data.publish is True
    assert data.grade_score == 72.5


def test_grade_score_minimum_boundary() -> None:
    """grade_score of 0.0 is valid."""
    data = GradeSubmissionIn(grade_score=0.0, grade_feedback="No marks awarded.")
    assert data.grade_score == 0.0


def test_grade_score_maximum_boundary() -> None:
    """grade_score of 100.0 is valid."""
    data = GradeSubmissionIn(grade_score=100.0, grade_feedback="Perfect.")
    assert data.grade_score == 100.0


def test_grade_score_below_zero_rejected() -> None:
    """grade_score below 0 should fail validation."""
    with pytest.raises(Exception):
        GradeSubmissionIn(grade_score=-1.0, grade_feedback="Bad.")


def test_grade_score_above_100_rejected() -> None:
    """grade_score above 100 should fail validation."""
    with pytest.raises(Exception):
        GradeSubmissionIn(grade_score=101.0, grade_feedback="Too high.")


def test_grade_feedback_empty_rejected() -> None:
    """Empty grade_feedback should fail validation (min_length=1)."""
    with pytest.raises(Exception):
        GradeSubmissionIn(grade_score=50.0, grade_feedback="")


def test_announcement_scope_validator() -> None:
    """AnnouncementIn rejects invalid scope values."""
    from app.modules.admin.schemas import AnnouncementIn

    with pytest.raises(Exception):
        AnnouncementIn(title="Hi", body="Hello", scope="unknown")


def test_announcement_scope_course_valid() -> None:
    from app.modules.admin.schemas import AnnouncementIn

    a = AnnouncementIn(
        title="Welcome",
        body="Hello students",
        scope="course",
        course_id=uuid.uuid4(),
    )
    assert a.scope == "course"


def test_announcement_scope_platform_valid() -> None:
    from app.modules.admin.schemas import AnnouncementIn

    a = AnnouncementIn(title="News", body="Platform update", scope="platform")
    assert a.scope == "platform"
    assert a.course_id is None
