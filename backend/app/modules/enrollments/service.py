"""Business logic for enrollment, lesson progress, notes, and bookmarks."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    AlreadyEnrolled,
    CourseNotEnrollable,
    CourseNotFound,
    EnrollmentNotFound,
    LessonNotFound,
    NoteNotFound,
    NotEnrolled,
)
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress, UserBookmark, UserNote
from app.db.models.program import ProgramEnrollment, ProgramStep
from app.modules.programs.unlock import LessonInfo, assert_lesson_accessible
from app.modules.enrollments.schemas import (
    ContinueLearningItem,
    CourseProgressOut,
    LessonProgressDetail,
)

# ── Progress rank map ──────────────────────────────────────────────────────────

_PROGRESS_RANK: dict[str, int] = {
    "not_started": 0,
    "in_progress": 1,
    "completed": 2,
}


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _compute_progress_pct(total: int, completed: int) -> float:
    """Return the completion percentage rounded to one decimal place.

    Args:
        total: Total number of lessons in the course.
        completed: Number of lessons with status ``"completed"``.

    Returns:
        A float between ``0.0`` and ``100.0``.
    """
    if total == 0:
        return 0.0
    return round(completed / total * 100, 1)


def _is_enrollable(course: Course) -> bool:
    """Return ``True`` if the course can be directly enrolled in by a student.

    A course is enrollable when it is published, not archived, and free
    (``price_cents == 0``).  Paid course gating is handled in Sprint 5.

    Args:
        course: The ``Course`` ORM instance to evaluate.

    Returns:
        ``True`` if the course is published, not archived, and free.
    """
    return (
        course.status == "published"
        and course.archived_at is None
        and course.price_cents == 0
    )


# ── Internal DB helpers ────────────────────────────────────────────────────────

async def _get_active_enrollment(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> Enrollment:
    """Return the active enrollment for a user–course pair or raise ``NotEnrolled``.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        course_id: UUID of the course.

    Returns:
        The active ``Enrollment`` ORM instance.

    Raises:
        NotEnrolled: If no active enrollment exists for this user and course.
    """
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
            Enrollment.status.in_(["active", "completed"]),
        )
    )
    if not enrollment:
        raise NotEnrolled()
    return enrollment


async def _get_lesson_with_chapter(
    db: AsyncSession, lesson_id: uuid.UUID
) -> tuple[Lesson, uuid.UUID]:
    """Fetch a lesson with its chapter eagerly loaded, returning the course ID.

    Args:
        db: Async database session.
        lesson_id: UUID of the lesson to load.

    Returns:
        A tuple of ``(lesson, course_id)`` where ``course_id`` is derived from
        the lesson's parent chapter.

    Raises:
        LessonNotFound: If no lesson with that ID exists.
    """
    lesson = await db.scalar(
        select(Lesson)
        .where(Lesson.id == lesson_id)
        .options(selectinload(Lesson.chapter))
    )
    if not lesson:
        raise LessonNotFound()
    return lesson, lesson.chapter.course_id


async def _load_enrollment_with_course(
    db: AsyncSession, enrollment_id: uuid.UUID
) -> Enrollment:
    """Fetch an enrollment by primary key with its course eagerly loaded.

    Args:
        db: Async database session.
        enrollment_id: UUID of the enrollment to load.

    Returns:
        The ``Enrollment`` ORM instance with ``course`` loaded.

    Raises:
        EnrollmentNotFound: If no enrollment with that ID exists.
    """
    enrollment = await db.scalar(
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(selectinload(Enrollment.course))
    )
    if not enrollment:
        raise EnrollmentNotFound()
    return enrollment


# ── Program unlock context (AL-BE-7) ──────────────────────────────────────────

async def _get_program_lesson_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> list[LessonInfo] | None:
    """Return the ordered LessonInfo list for a course if it belongs to the student's active program.

    This is the DB-side half of the AL-BE-7 unlock gate.  Returns ``None``
    (skip the gate) when:

    - The student has no active ``ProgramEnrollment``, or
    - The course is not a step in the active program.

    When ``None`` is returned ``save_progress`` proceeds without the unlock
    check, preserving backward compatibility for standalone course enrollments.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        course_id: UUID of the course the lesson belongs to.

    Returns:
        An ordered list of :class:`LessonInfo` for the course (sorted by
        chapter.position ASC, lesson.position ASC), or ``None``.
    """
    # 1. Active ProgramEnrollment
    pe = await db.scalar(
        select(ProgramEnrollment).where(
            ProgramEnrollment.user_id == user_id,
            ProgramEnrollment.status == "active",
        )
    )
    if pe is None:
        return None

    # 2. Check that this course is actually a step in the active program
    step = await db.scalar(
        select(ProgramStep).where(
            ProgramStep.program_id == pe.program_id,
            ProgramStep.course_id == course_id,
        )
    )
    if step is None:
        return None

    # 3. Load course with chapters and lessons
    course = await db.scalar(
        select(Course)
        .where(Course.id == course_id)
        .options(selectinload(Course.chapters).selectinload(Chapter.lessons))
    )
    if course is None:
        return None

    # Build chapter lookup to avoid lazy-load triggers on lesson.chapter
    chapter_by_lesson_id: dict[uuid.UUID, Chapter] = {}
    for ch in course.chapters:
        for ls in ch.lessons:
            chapter_by_lesson_id[ls.id] = ch

    lessons_in_order: list[Lesson] = [
        ls
        for ch in sorted(course.chapters, key=lambda c: c.position)
        for ls in sorted(ch.lessons, key=lambda l: l.position)
    ]
    lesson_ids = [ls.id for ls in lessons_in_order]

    # 4. Lesson progress rows for existing entries
    progress_rows = await db.scalars(
        select(LessonProgress).where(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id.in_(lesson_ids),
        )
    )
    progress_by_lesson: dict[uuid.UUID, LessonProgress] = {
        p.lesson_id: p for p in progress_rows
    }

    return [
        LessonInfo(
            lesson_id=ls.id,
            chapter_id=ls.chapter_id,
            chapter_title=chapter_by_lesson_id[ls.id].title,
            lesson_title=ls.title,
            position_in_course=idx,
            is_locked=ls.is_locked,
            progress_status=(
                progress_by_lesson[ls.id].status
                if ls.id in progress_by_lesson
                else "not_started"
            ),
            completed_at=(
                progress_by_lesson[ls.id].completed_at
                if ls.id in progress_by_lesson
                else None
            ),
        )
        for idx, ls in enumerate(lessons_in_order)
    ]


# ── Enrollment ─────────────────────────────────────────────────────────────────

async def enroll_paid(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    payment_id: uuid.UUID,
) -> Enrollment:
    """Create or reactivate an enrollment for a paid course after successful payment.

    Unlike ``enroll()``, this bypasses the free-course check and links the
    payment record.  Called exclusively from the Stripe webhook handler.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        course_id: UUID of the purchased course.
        payment_id: UUID of the completed ``Payment`` row.

    Returns:
        The active ``Enrollment`` ORM instance with course loaded.

    Raises:
        CourseNotFound: If the course does not exist.
    """
    course = await db.get(Course, course_id)
    if not course:
        raise CourseNotFound()

    existing = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
        )
    )

    if existing:
        if existing.status == "active":
            return await _load_enrollment_with_course(db, existing.id)
        existing.status = "active"
        existing.completed_at = None
        existing.payment_id = str(payment_id)
        await db.commit()
        return await _load_enrollment_with_course(db, existing.id)

    enrollment = Enrollment(
        user_id=user_id,
        course_id=course_id,
        status="active",
        payment_id=str(payment_id),
    )
    db.add(enrollment)
    await db.commit()
    return await _load_enrollment_with_course(db, enrollment.id)


async def enroll(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> Enrollment:
    """Enroll a student in a free published course.

    If a previous (unenrolled) record exists for this user–course pair, it is
    restored to ``active`` rather than creating a duplicate.  Prior lesson
    progress is preserved on re-enroll.

    Args:
        db: Async database session.
        user_id: UUID of the student enrolling.
        course_id: UUID of the course to enroll in.

    Returns:
        The active ``Enrollment`` ORM instance with course loaded.

    Raises:
        CourseNotFound: If the course does not exist.
        CourseNotEnrollable: If the course is not published, is archived, or has a non-zero price.
        AlreadyEnrolled: If the student is already actively enrolled in this course.
    """
    course = await db.get(Course, course_id)
    if not course:
        raise CourseNotFound()
    if not _is_enrollable(course):
        raise CourseNotEnrollable()

    existing = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
        )
    )

    if existing:
        if existing.status == "active":
            raise AlreadyEnrolled()
        # Restore unenrolled or completed enrollment
        existing.status = "active"
        existing.completed_at = None
        await db.commit()
        return await _load_enrollment_with_course(db, existing.id)

    enrollment = Enrollment(user_id=user_id, course_id=course_id, status="active")
    db.add(enrollment)
    await db.commit()
    return await _load_enrollment_with_course(db, enrollment.id)


async def unenroll(
    db: AsyncSession, user_id: uuid.UUID, enrollment_id: uuid.UUID
) -> None:
    """Soft-delete an enrollment by setting its status to ``unenrolled``.

    Args:
        db: Async database session.
        user_id: UUID of the authenticated student; used to verify ownership.
        enrollment_id: UUID of the enrollment to unenroll from.

    Raises:
        EnrollmentNotFound: If the enrollment does not exist or does not belong to this user.
    """
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.id == enrollment_id,
            Enrollment.user_id == user_id,
        )
    )
    if not enrollment:
        raise EnrollmentNotFound()
    enrollment.status = "unenrolled"
    await db.commit()


async def list_enrollments(
    db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int
) -> tuple[list[Enrollment], int]:
    """Return a paginated list of a student's enrollments with course data.

    All statuses are included so the student can see their full history.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(enrollments, total)`` where ``total`` is the unfiltered
        count of this student's enrollments.
    """
    base = select(Enrollment).where(Enrollment.user_id == user_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    result = await db.scalars(
        base.options(selectinload(Enrollment.course))
        .order_by(Enrollment.enrolled_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.all()), total or 0


# ── Progress ───────────────────────────────────────────────────────────────────

async def save_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID,
    status: str,
    watch_seconds: int | None,
) -> LessonProgress:
    """Upsert lesson progress for an enrolled student.

    Status only advances forward (``not_started`` → ``in_progress`` →
    ``completed``); a lower-rank status in the payload is silently ignored
    while ``watch_seconds`` is still updated.

    After marking a lesson ``completed``, checks whether all lessons in the
    course are now complete and updates the enrollment to ``completed`` if so.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        lesson_id: UUID of the lesson to update.
        status: Target progress state.
        watch_seconds: Current playback position in seconds; ``None`` leaves the
            existing value unchanged.

    Returns:
        The upserted ``LessonProgress`` ORM instance.

    Raises:
        LessonNotFound: If the lesson does not exist.
        NotEnrolled: If the student is not actively enrolled in this lesson's course.
    """
    lesson, course_id = await _get_lesson_with_chapter(db, lesson_id)
    await _get_active_enrollment(db, user_id, course_id)

    # AL-BE-7: Unlock gate — skipped for standalone courses not in any program step
    lesson_infos = await _get_program_lesson_context(db, user_id, course_id)
    if lesson_infos is not None:
        assert_lesson_accessible(lesson_infos, lesson_id)

    existing = await db.scalar(
        select(LessonProgress).where(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id == lesson_id,
        )
    )

    if existing:
        if _PROGRESS_RANK[status] > _PROGRESS_RANK[existing.status]:
            existing.status = status
            if status == "completed" and not existing.completed_at:
                existing.completed_at = datetime.now(UTC)
        if watch_seconds is not None:
            existing.watch_seconds = watch_seconds
        await db.commit()
        await db.refresh(existing)
        progress = existing
    else:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson_id,
            status=status,
            watch_seconds=watch_seconds or 0,
            completed_at=datetime.now(UTC) if status == "completed" else None,
        )
        db.add(progress)
        await db.commit()
        await db.refresh(progress)

    if progress.status == "completed":
        await _maybe_complete_enrollment(db, user_id, course_id)

    return progress


async def _maybe_complete_enrollment(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> None:
    """Mark an enrollment as completed if all lessons in the course are done.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        course_id: UUID of the course to check.
    """
    total_lessons = await db.scalar(
        select(func.count(Lesson.id))
        .join(Chapter, Lesson.chapter_id == Chapter.id)
        .where(Chapter.course_id == course_id)
    )
    if not total_lessons:
        return

    completed_lessons = await db.scalar(
        select(func.count(LessonProgress.id))
        .join(Lesson, LessonProgress.lesson_id == Lesson.id)
        .join(Chapter, Lesson.chapter_id == Chapter.id)
        .where(
            Chapter.course_id == course_id,
            LessonProgress.user_id == user_id,
            LessonProgress.status == "completed",
        )
    )

    if completed_lessons == total_lessons:
        enrollment = await _get_active_enrollment(db, user_id, course_id)
        enrollment.status = "completed"
        enrollment.completed_at = datetime.now(UTC)
        await db.commit()

        # Lazy import avoids circular dependency (certificates → enrollments)
        from app.modules.certificates import service as certificate_service
        await certificate_service.check_and_issue(db, user_id, course_id)


async def get_course_progress(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> CourseProgressOut:
    """Return the student's progress across all lessons in a course.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        course_id: UUID of the course.

    Returns:
        A ``CourseProgressOut`` with total/completed counts, a percentage, and
        a per-lesson breakdown ordered by chapter then lesson position.

    Raises:
        CourseNotFound: If the course does not exist.
        NotEnrolled: If the student is not actively enrolled.
    """
    await _get_active_enrollment(db, user_id, course_id)

    course = await db.scalar(
        select(Course)
        .where(Course.id == course_id)
        .options(
            selectinload(Course.chapters).selectinload(Chapter.lessons)
        )
    )
    if not course:
        raise CourseNotFound()

    lessons_in_order = [
        lesson
        for chapter in sorted(course.chapters, key=lambda c: c.position)
        for lesson in sorted(chapter.lessons, key=lambda ls: ls.position)
    ]

    lesson_ids = [ls.id for ls in lessons_in_order]
    progress_by_lesson: dict[uuid.UUID, LessonProgress] = {}
    if lesson_ids:
        rows = await db.scalars(
            select(LessonProgress).where(
                LessonProgress.user_id == user_id,
                LessonProgress.lesson_id.in_(lesson_ids),
            )
        )
        progress_by_lesson = {p.lesson_id: p for p in rows}

    details: list[LessonProgressDetail] = []
    completed_count = 0
    for lesson in lessons_in_order:
        prog = progress_by_lesson.get(lesson.id)
        s = prog.status if prog else "not_started"
        if s == "completed":
            completed_count += 1
        details.append(
            LessonProgressDetail(
                lesson_id=lesson.id,
                lesson_title=lesson.title,
                status=s,
                watch_seconds=prog.watch_seconds if prog else 0,
                completed_at=prog.completed_at if prog else None,
            )
        )

    return CourseProgressOut(
        course_id=course_id,
        total_lessons=len(lessons_in_order),
        completed_lessons=completed_count,
        progress_pct=_compute_progress_pct(len(lessons_in_order), completed_count),
        lessons=details,
    )


async def get_continue_learning(
    db: AsyncSession, user_id: uuid.UUID
) -> list[ContinueLearningItem]:
    """Return the next incomplete lesson for each of the student's active enrollments.

    Courses where all lessons are completed are excluded from the result.

    Args:
        db: Async database session.
        user_id: UUID of the student.

    Returns:
        An ordered list of ``ContinueLearningItem``, one per active enrollment
        that still has incomplete lessons.
    """
    enrollments = list(
        await db.scalars(
            select(Enrollment)
            .where(Enrollment.user_id == user_id, Enrollment.status == "active")
            .options(
                selectinload(Enrollment.course)
                .selectinload(Course.chapters)
                .selectinload(Chapter.lessons)
            )
        )
    )

    if not enrollments:
        return []

    # Collect all lesson IDs across all enrolled courses in a single query
    all_lesson_ids: list[uuid.UUID] = [
        lesson.id
        for enrollment in enrollments
        for chapter in enrollment.course.chapters
        for lesson in chapter.lessons
    ]

    completed_lesson_ids: set[uuid.UUID] = set()
    if all_lesson_ids:
        rows = await db.scalars(
            select(LessonProgress.lesson_id).where(
                LessonProgress.user_id == user_id,
                LessonProgress.lesson_id.in_(all_lesson_ids),
                LessonProgress.status == "completed",
            )
        )
        completed_lesson_ids = set(rows.all())

    result: list[ContinueLearningItem] = []
    for enrollment in enrollments:
        lessons_in_order = [
            lesson
            for chapter in sorted(enrollment.course.chapters, key=lambda c: c.position)
            for lesson in sorted(chapter.lessons, key=lambda ls: ls.position)
        ]
        next_lesson = next(
            (ls for ls in lessons_in_order if ls.id not in completed_lesson_ids),
            None,
        )
        if next_lesson:
            result.append(
                ContinueLearningItem(
                    course_id=enrollment.course_id,
                    course_title=enrollment.course.title,
                    course_slug=enrollment.course.slug,
                    next_lesson_id=next_lesson.id,
                    next_lesson_title=next_lesson.title,
                )
            )

    return result


# ── Notes ──────────────────────────────────────────────────────────────────────

async def upsert_note(
    db: AsyncSession,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID,
    content: str,
) -> UserNote:
    """Create or update the student's note on a lesson.

    One note per ``(user_id, lesson_id)`` pair.  If a note already exists its
    ``content`` is updated in place; otherwise a new row is inserted.

    Args:
        db: Async database session.
        user_id: UUID of the note author.
        lesson_id: UUID of the lesson to attach the note to.
        content: Note body text.

    Returns:
        The created or updated ``UserNote`` ORM instance.

    Raises:
        LessonNotFound: If the lesson does not exist.
        NotEnrolled: If the student is not actively enrolled in this lesson's course.
    """
    _, course_id = await _get_lesson_with_chapter(db, lesson_id)
    await _get_active_enrollment(db, user_id, course_id)

    existing = await db.scalar(
        select(UserNote).where(
            UserNote.user_id == user_id,
            UserNote.lesson_id == lesson_id,
        )
    )
    if existing:
        existing.content = content
        await db.commit()
        await db.refresh(existing)
        return existing

    note = UserNote(user_id=user_id, lesson_id=lesson_id, content=content)
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def get_note(
    db: AsyncSession, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> UserNote:
    """Fetch the student's note on a lesson.

    Args:
        db: Async database session.
        user_id: UUID of the note author.
        lesson_id: UUID of the lesson.

    Returns:
        The ``UserNote`` ORM instance.

    Raises:
        LessonNotFound: If the lesson does not exist.
        NotEnrolled: If the student is not actively enrolled in this lesson's course.
        NoteNotFound: If the student has no note on this lesson.
    """
    _, course_id = await _get_lesson_with_chapter(db, lesson_id)
    await _get_active_enrollment(db, user_id, course_id)

    note = await db.scalar(
        select(UserNote).where(
            UserNote.user_id == user_id,
            UserNote.lesson_id == lesson_id,
        )
    )
    if not note:
        raise NoteNotFound()
    return note


async def delete_note(
    db: AsyncSession, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> None:
    """Delete the student's note on a lesson.

    Args:
        db: Async database session.
        user_id: UUID of the note author.
        lesson_id: UUID of the lesson.

    Raises:
        LessonNotFound: If the lesson does not exist.
        NotEnrolled: If the student is not actively enrolled in this lesson's course.
        NoteNotFound: If the student has no note on this lesson.
    """
    note = await get_note(db, user_id, lesson_id)
    await db.delete(note)
    await db.commit()


async def list_notes(
    db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int
) -> tuple[list[UserNote], int]:
    """Return a paginated list of the student's notes with full lesson context.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(notes, total)`` where ``total`` is the unfiltered count
        of this student's notes.
    """
    base = select(UserNote).where(UserNote.user_id == user_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    result = await db.scalars(
        base.options(
            selectinload(UserNote.lesson)
            .selectinload(Lesson.chapter)
            .selectinload(Chapter.course)
        )
        .order_by(UserNote.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.all()), total or 0


# ── Bookmarks ──────────────────────────────────────────────────────────────────

async def set_bookmark(
    db: AsyncSession,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID,
    *,
    bookmarked: bool,
) -> bool:
    """Set bookmark state on a lesson idempotently.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        lesson_id: UUID of the lesson to bookmark.
        bookmarked: Desired bookmark state.

    Returns:
        The resulting bookmark state.

    Raises:
        LessonNotFound: If the lesson does not exist.
        NotEnrolled: If the student is not actively enrolled in this lesson's course.
    """
    _, course_id = await _get_lesson_with_chapter(db, lesson_id)
    await _get_active_enrollment(db, user_id, course_id)

    existing = await db.scalar(
        select(UserBookmark).where(
            UserBookmark.user_id == user_id,
            UserBookmark.lesson_id == lesson_id,
        )
    )
    if bookmarked:
        if existing is None:
            db.add(UserBookmark(user_id=user_id, lesson_id=lesson_id))
            await db.commit()
        return True

    if existing is not None:
        await db.delete(existing)
        await db.commit()
    return False


async def toggle_bookmark(
    db: AsyncSession, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> bool:
    """Toggle a bookmark on a lesson, creating it if absent or deleting it if present."""
    existing = await db.scalar(
        select(UserBookmark).where(
            UserBookmark.user_id == user_id,
            UserBookmark.lesson_id == lesson_id,
        )
    )
    return await set_bookmark(
        db,
        user_id,
        lesson_id,
        bookmarked=existing is None,
    )


async def list_bookmarks(
    db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int
) -> tuple[list[UserBookmark], int]:
    """Return a paginated list of the student's bookmarks with full lesson context.

    Each bookmark is loaded with its lesson, the lesson's chapter, and the
    chapter's course — providing all data needed for the bookmark list UI.

    Args:
        db: Async database session.
        user_id: UUID of the student.
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(bookmarks, total)`` where ``total`` is the unfiltered count
        of this student's bookmarks.
    """
    base = select(UserBookmark).where(UserBookmark.user_id == user_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    result = await db.scalars(
        base.options(
            selectinload(UserBookmark.lesson)
            .selectinload(Lesson.chapter)
            .selectinload(Chapter.course)
        )
        .order_by(UserBookmark.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.all()), total or 0
