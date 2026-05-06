"""Unit tests for the pure unlock engine (AL-BE-7).

All tests operate on plain dataclasses — no database, no async fixtures.
"""

import uuid

import pytest

from app.core.exceptions import LessonLocked, LessonNotFound
from app.modules.programs.unlock import (
    LessonInfo,
    StepInfo,
    assert_lesson_accessible,
    compute_accessible_lessons,
    find_current_step,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _step(
    position: int,
    *,
    is_required: bool = True,
    status: str | None = None,
) -> StepInfo:
    return StepInfo(
        step_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        position=position,
        is_required=is_required,
        course_enrollment_status=status,
    )


def _lesson(
    idx: int,
    *,
    is_locked: bool = False,
    progress: str = "not_started",
) -> LessonInfo:
    return LessonInfo(
        lesson_id=uuid.uuid4(),
        chapter_id=uuid.uuid4(),
        chapter_title="Chapter",
        lesson_title=f"Lesson {idx}",
        position_in_course=idx,
        is_locked=is_locked,
        progress_status=progress,
        completed_at=None,
    )


# ── find_current_step ──────────────────────────────────────────────────────────

class TestFindCurrentStep:
    def test_first_step_always_unlocked(self) -> None:
        steps = [_step(1)]
        result = find_current_step(steps)
        assert result is not None
        assert result.position == 1

    def test_single_step_completed_returns_none(self) -> None:
        steps = [_step(1, status="completed")]
        assert find_current_step(steps) is None

    def test_required_step1_incomplete_blocks_step2(self) -> None:
        steps = [_step(1), _step(2)]
        result = find_current_step(steps)
        assert result is not None
        assert result.position == 1

    def test_required_step1_completed_unlocks_step2(self) -> None:
        steps = [_step(1, status="completed"), _step(2)]
        result = find_current_step(steps)
        assert result is not None
        assert result.position == 2

    def test_optional_step_incomplete_does_not_block_successor(self) -> None:
        # step1 is optional and not done; step2 is required
        # step1 is the current step (unlocked, not complete) — optional steps
        # cannot gate later steps but they are still the "current" focus
        steps = [_step(1, is_required=False), _step(2)]
        result = find_current_step(steps)
        assert result is not None
        assert result.position == 1

    def test_optional_step_does_not_block_required_successor(self) -> None:
        # step1 required + completed, step2 optional + not done, step3 required
        # step2 is the current step (first unlocked incomplete)
        steps = [
            _step(1, is_required=True, status="completed"),
            _step(2, is_required=False),
            _step(3, is_required=True),
        ]
        result = find_current_step(steps)
        assert result is not None
        assert result.position == 2

    def test_all_required_completed_returns_none(self) -> None:
        steps = [
            _step(1, status="completed"),
            _step(2, status="completed"),
            _step(3, status="completed"),
        ]
        assert find_current_step(steps) is None

    def test_empty_step_list_returns_none(self) -> None:
        assert find_current_step([]) is None

    def test_three_steps_second_is_current(self) -> None:
        steps = [
            _step(1, status="completed"),
            _step(2),
            _step(3),
        ]
        result = find_current_step(steps)
        assert result is not None
        assert result.position == 2


# ── compute_accessible_lessons ─────────────────────────────────────────────────

class TestComputeAccessibleLessons:
    def test_first_lesson_accessible_when_not_locked(self) -> None:
        lessons = [_lesson(0)]
        results = compute_accessible_lessons(lessons)
        assert results[0].is_accessible is True
        assert results[0].is_admin_locked is False

    def test_first_lesson_blocked_by_admin_lock(self) -> None:
        lessons = [_lesson(0, is_locked=True)]
        results = compute_accessible_lessons(lessons)
        assert results[0].is_accessible is False
        assert results[0].is_admin_locked is True

    def test_second_lesson_accessible_when_first_completed(self) -> None:
        lessons = [_lesson(0, progress="completed"), _lesson(1)]
        results = compute_accessible_lessons(lessons)
        assert results[1].is_accessible is True

    def test_second_lesson_blocked_when_first_not_completed(self) -> None:
        for prog in ("not_started", "in_progress"):
            lessons = [_lesson(0, progress=prog), _lesson(1)]
            results = compute_accessible_lessons(lessons)
            assert results[1].is_accessible is False, f"expected blocked for progress={prog}"

    def test_admin_lock_overrides_prior_completion(self) -> None:
        lessons = [_lesson(0, progress="completed"), _lesson(1, is_locked=True)]
        results = compute_accessible_lessons(lessons)
        assert results[1].is_accessible is False
        assert results[1].is_admin_locked is True

    def test_chain_breaks_at_first_incomplete(self) -> None:
        lessons = [_lesson(0), _lesson(1), _lesson(2)]
        results = compute_accessible_lessons(lessons)
        assert results[0].is_accessible is True
        assert results[1].is_accessible is False
        assert results[2].is_accessible is False

    def test_all_lessons_accessible_when_all_preceding_completed(self) -> None:
        lessons = [
            _lesson(0, progress="completed"),
            _lesson(1, progress="completed"),
            _lesson(2),
        ]
        results = compute_accessible_lessons(lessons)
        assert all(r.is_accessible for r in results)

    def test_empty_lesson_list_returns_empty(self) -> None:
        assert compute_accessible_lessons([]) == []

    def test_result_preserves_progress_and_metadata(self) -> None:
        lesson = _lesson(0, progress="in_progress")
        results = compute_accessible_lessons([lesson])
        assert results[0].progress_status == "in_progress"
        assert results[0].lesson_id == lesson.lesson_id
        assert results[0].lesson_title == lesson.lesson_title


# ── assert_lesson_accessible ───────────────────────────────────────────────────

class TestAssertLessonAccessible:
    def test_passes_for_first_accessible_lesson(self) -> None:
        lesson = _lesson(0)
        assert_lesson_accessible([lesson], lesson.lesson_id)  # no exception

    def test_raises_lesson_locked_for_admin_locked(self) -> None:
        lesson = _lesson(0, is_locked=True)
        with pytest.raises(LessonLocked):
            assert_lesson_accessible([lesson], lesson.lesson_id)

    def test_raises_lesson_locked_for_sequential_block(self) -> None:
        l0 = _lesson(0)  # not completed
        l1 = _lesson(1)
        with pytest.raises(LessonLocked):
            assert_lesson_accessible([l0, l1], l1.lesson_id)

    def test_does_not_raise_for_second_lesson_after_first_completed(self) -> None:
        l0 = _lesson(0, progress="completed")
        l1 = _lesson(1)
        assert_lesson_accessible([l0, l1], l1.lesson_id)  # no exception

    def test_raises_lesson_not_found_for_unknown_id(self) -> None:
        lesson = _lesson(0)
        with pytest.raises(LessonNotFound):
            assert_lesson_accessible([lesson], uuid.uuid4())
