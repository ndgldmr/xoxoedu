"""Pure unlock engine for program-step and lesson progression (AL-BE-7).

All functions in this module are pure — no database access, no SQLAlchemy
imports.  They operate on lightweight dataclasses so they can be unit-tested
without any DB fixtures or async infrastructure.

The DB-backed callers (``programs.service`` and ``enrollments.service``)
assemble the dataclasses from ORM data and then delegate unlock decisions here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


# ── Input dataclasses ──────────────────────────────────────────────────────────

@dataclass
class StepInfo:
    """Everything the engine needs to evaluate one ProgramStep.

    Attributes:
        step_id: PK of the ProgramStep row.
        course_id: FK to the Course this step maps to.
        position: 1-based ordering within the program.
        is_required: When ``True`` this step's completion gates later steps.
        course_enrollment_status: The student's Enrollment.status for this
            course, or ``None`` when no Enrollment row exists.
    """

    step_id: uuid.UUID
    course_id: uuid.UUID
    position: int
    is_required: bool
    course_enrollment_status: str | None


@dataclass
class LessonInfo:
    """Everything the engine needs to evaluate one Lesson within a step's course.

    Attributes:
        lesson_id: PK of the Lesson row.
        chapter_id: PK of the parent Chapter.
        chapter_title: Display title of the parent chapter.
        lesson_title: Display title of the lesson.
        position_in_course: 0-based flat index after sorting all lessons by
            (chapter.position ASC, lesson.position ASC).
        is_locked: Mirrors ``Lesson.is_locked`` — admin hard-lock.  When
            ``True`` the lesson is always inaccessible regardless of sequence.
        progress_status: Student's progress on this lesson
            (``"not_started"`` | ``"in_progress"`` | ``"completed"``).
            Defaults to ``"not_started"`` when no LessonProgress row exists.
        completed_at: Timestamp when the lesson was completed, or ``None``.
    """

    lesson_id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_title: str
    lesson_title: str
    position_in_course: int
    is_locked: bool
    progress_status: str
    completed_at: datetime | None


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class AccessibleLessonResult:
    """Annotated lesson entry produced by :func:`compute_accessible_lessons`.

    Attributes:
        lesson_id: PK of the Lesson row.
        lesson_title: Display title.
        chapter_id: PK of the parent Chapter.
        chapter_title: Display title of the parent chapter.
        position_in_course: 0-based flat index within the course.
        is_accessible: ``True`` when the student may interact with this lesson.
        is_admin_locked: ``True`` when ``Lesson.is_locked`` is set — reported
            separately so the frontend can show a distinct "admin locked" state.
        progress_status: Student's current progress status.
        completed_at: Completion timestamp or ``None``.
    """

    lesson_id: uuid.UUID
    lesson_title: str
    chapter_id: uuid.UUID
    chapter_title: str
    position_in_course: int
    is_accessible: bool
    is_admin_locked: bool
    progress_status: str
    completed_at: datetime | None


# ── Step unlock ────────────────────────────────────────────────────────────────

def find_current_step(steps: list[StepInfo]) -> StepInfo | None:
    """Return the first unlocked, non-completed step in the program.

    **Unlock rule** (steps must be passed in ascending ``position`` order):

    - The step at position 1 is always unlocked.
    - A step at position P (P > 1) is unlocked iff every *required* step at
      positions < P has ``course_enrollment_status == "completed"``.
    - Non-required steps that are still incomplete do **not** block later steps.

    **"Current" step**: the first unlocked step whose course is not yet
    completed.  Once a student completes a step the engine advances to the
    next unlocked one.

    Returns:
        The current :class:`StepInfo`, or ``None`` when every step is
        completed (the program is finished).

    Args:
        steps: Full ordered step list for the program.  The caller is
            responsible for sorting by ``position`` ascending before calling.
    """
    all_required_done = True  # vacuously true; evaluated before position 1
    for step in steps:
        unlocked = (step.position == 1) or all_required_done
        if unlocked and step.course_enrollment_status != "completed":
            return step
        # Update running flag — only required incomplete steps block successors
        if step.is_required and step.course_enrollment_status != "completed":
            all_required_done = False
    return None  # every step completed → program finished


# ── Lesson unlock ──────────────────────────────────────────────────────────────

def compute_accessible_lessons(
    lessons: list[LessonInfo],
) -> list[AccessibleLessonResult]:
    """Return each lesson annotated with its computed accessibility state.

    **Accessibility rule** for the lesson at flat index N:

    - ``is_admin_locked = lesson.is_locked``
    - ``prev_completed = (N == 0) or (lessons[N-1].progress_status == "completed")``
    - ``is_accessible = prev_completed and not lesson.is_locked``

    The admin hard-lock (``is_locked == True``) always blocks access,
    including the very first lesson.  ``is_accessible`` and ``is_admin_locked``
    are returned as separate fields so the frontend can show distinct UI states.

    Args:
        lessons: Flat ordered lesson list for the course.  Must be sorted by
            (chapter.position ASC, lesson.position ASC) before calling.
            Each entry must have ``progress_status`` pre-populated from the
            student's LessonProgress rows (default ``"not_started"`` when no
            row exists).

    Returns:
        A list of :class:`AccessibleLessonResult` in the same order as the
        input, one entry per lesson.
    """
    results: list[AccessibleLessonResult] = []
    for i, lesson in enumerate(lessons):
        prev_completed = (i == 0) or (lessons[i - 1].progress_status == "completed")
        is_accessible = prev_completed and not lesson.is_locked
        results.append(
            AccessibleLessonResult(
                lesson_id=lesson.lesson_id,
                lesson_title=lesson.lesson_title,
                chapter_id=lesson.chapter_id,
                chapter_title=lesson.chapter_title,
                position_in_course=lesson.position_in_course,
                is_accessible=is_accessible,
                is_admin_locked=lesson.is_locked,
                progress_status=lesson.progress_status,
                completed_at=lesson.completed_at,
            )
        )
    return results


def assert_lesson_accessible(
    lessons: list[LessonInfo],
    lesson_id: uuid.UUID,
) -> None:
    """Raise if ``lesson_id`` is not accessible in the given lesson sequence.

    Computes the accessibility list via :func:`compute_accessible_lessons` and
    looks up the entry matching ``lesson_id``.

    Args:
        lessons: Full flat ordered lesson list for the course (same contract
            as :func:`compute_accessible_lessons`).
        lesson_id: UUID of the lesson the student is trying to access.

    Raises:
        LessonNotFound: If ``lesson_id`` is not present in ``lessons``.
        LessonLocked: If the matching lesson's ``is_accessible`` is ``False``.
    """
    # Local imports keep this module free of circular dependencies at import
    # time; exceptions.py never imports from modules/programs.
    from app.core.exceptions import LessonLocked, LessonNotFound

    results = compute_accessible_lessons(lessons)
    for result in results:
        if result.lesson_id == lesson_id:
            if not result.is_accessible:
                raise LessonLocked()
            return
    raise LessonNotFound()
