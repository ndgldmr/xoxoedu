"""Unit tests for pure enrollment and progress business logic."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.enrollments.service import (
    _PROGRESS_RANK,
    _compute_progress_pct,
    _is_enrollable,
)


# ── _compute_progress_pct ──────────────────────────────────────────────────────

def test_progress_pct_zero_when_no_lessons() -> None:
    """Returns 0.0 for a course with no lessons to avoid division by zero."""
    assert _compute_progress_pct(total=0, completed=0) == 0.0


def test_progress_pct_zero_when_none_completed() -> None:
    assert _compute_progress_pct(total=5, completed=0) == 0.0


def test_progress_pct_partial() -> None:
    assert _compute_progress_pct(total=4, completed=1) == 25.0


def test_progress_pct_full() -> None:
    assert _compute_progress_pct(total=3, completed=3) == 100.0


def test_progress_pct_rounds_to_one_decimal() -> None:
    # 1/3 = 33.333... should round to 33.3
    assert _compute_progress_pct(total=3, completed=1) == 33.3


# ── _is_enrollable ─────────────────────────────────────────────────────────────

def _make_course(**overrides) -> SimpleNamespace:
    """Build a minimal course-like object with defaults for enrollability testing.

    Uses ``SimpleNamespace`` to avoid SQLAlchemy ORM instrumentation overhead;
    ``_is_enrollable`` only reads ``status``, ``archived_at``, and ``price_cents``.
    """
    defaults = {"status": "published", "archived_at": None, "price_cents": 0}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_enrollable_published_free_not_archived() -> None:
    """A published, free, non-archived course is enrollable."""
    assert _is_enrollable(_make_course()) is True


def test_not_enrollable_draft_course() -> None:
    assert _is_enrollable(_make_course(status="draft")) is False


def test_not_enrollable_archived_course() -> None:
    archived_at = datetime(2025, 1, 1, tzinfo=UTC)
    assert _is_enrollable(_make_course(archived_at=archived_at)) is False


def test_not_enrollable_paid_course() -> None:
    assert _is_enrollable(_make_course(price_cents=999)) is False


def test_not_enrollable_archived_status() -> None:
    assert _is_enrollable(_make_course(status="archived")) is False


# ── _PROGRESS_RANK ─────────────────────────────────────────────────────────────

def test_progress_rank_ordering() -> None:
    """Progress statuses must rank in the correct forward-only order."""
    assert _PROGRESS_RANK["not_started"] < _PROGRESS_RANK["in_progress"]
    assert _PROGRESS_RANK["in_progress"] < _PROGRESS_RANK["completed"]


def test_progress_rank_covers_all_valid_statuses() -> None:
    assert set(_PROGRESS_RANK.keys()) == {"not_started", "in_progress", "completed"}
