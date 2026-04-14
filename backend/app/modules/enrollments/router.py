"""FastAPI router for enrollment, progress, notes, and bookmark endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.enrollments import service
from app.modules.enrollments.schemas import (
    BookmarkListItem,
    BookmarkToggleOut,
    EnrollmentOut,
    LessonProgressIn,
    LessonProgressOut,
    NoteIn,
    NoteListItem,
    NoteOut,
)

router = APIRouter(tags=["enrollments"])


# ── Enrollment ─────────────────────────────────────────────────────────────────

@router.post("/courses/{course_id}/enroll", status_code=201)
async def enroll(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Enroll the authenticated student in a free published course."""
    enrollment = await service.enroll(db, current_user.id, course_id)
    return ok(EnrollmentOut.model_validate(enrollment).model_dump())


@router.delete("/enrollments/{enrollment_id}", status_code=200)
async def unenroll(
    enrollment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Unenroll the authenticated student from a course (soft-delete)."""
    await service.unenroll(db, current_user.id, enrollment_id)
    return ok({"unenrolled": True})


@router.get("/users/me/enrollments")
async def list_enrollments(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List all enrollments for the authenticated student, ordered by most recent."""
    enrollments, total = await service.list_enrollments(db, current_user.id, skip, limit)
    return ok(
        [EnrollmentOut.model_validate(e).model_dump() for e in enrollments],
        meta={"total": total, "skip": skip, "limit": limit},
    )


# ── Progress ───────────────────────────────────────────────────────────────────

@router.post("/lessons/{lesson_id}/progress", status_code=200)
async def save_progress(
    lesson_id: uuid.UUID,
    body: LessonProgressIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Save or advance lesson progress for the authenticated student.

    Status transitions are forward-only.  Duplicate calls with the same or a
    lower status are accepted and update ``watch_seconds`` without regression.
    """
    progress = await service.save_progress(
        db, current_user.id, lesson_id, body.status, body.watch_seconds
    )
    return ok(LessonProgressOut.model_validate(progress).model_dump())


@router.get("/courses/{course_id}/progress")
async def get_course_progress(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return the authenticated student's full progress breakdown for a course."""
    progress = await service.get_course_progress(db, current_user.id, course_id)
    return ok(progress.model_dump())


@router.get("/users/me/continue")
async def get_continue_learning(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Return the next incomplete lesson for each of the student's active enrollments."""
    items = await service.get_continue_learning(db, current_user.id)
    return ok([item.model_dump() for item in items])


# ── Notes ──────────────────────────────────────────────────────────────────────

@router.get("/users/me/notes")
async def list_notes(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List all of the authenticated student's notes with lesson and course context."""
    notes, total = await service.list_notes(db, current_user.id, skip, limit)
    return ok(
        [NoteListItem.model_validate(n).model_dump() for n in notes],
        meta={"total": total, "skip": skip, "limit": limit},
    )


@router.post("/lessons/{lesson_id}/notes", status_code=200)
async def upsert_note(
    lesson_id: uuid.UUID,
    body: NoteIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Create or update the authenticated student's note on a lesson."""
    note = await service.upsert_note(db, current_user.id, lesson_id, body.content)
    return ok(NoteOut.model_validate(note).model_dump())


@router.get("/lessons/{lesson_id}/notes")
async def get_note(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Fetch the authenticated student's note on a lesson."""
    note = await service.get_note(db, current_user.id, lesson_id)
    return ok(NoteOut.model_validate(note).model_dump())


@router.delete("/lessons/{lesson_id}/notes", status_code=200)
async def delete_note(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Delete the authenticated student's note on a lesson."""
    await service.delete_note(db, current_user.id, lesson_id)
    return ok({"deleted": True})


# ── Bookmarks ──────────────────────────────────────────────────────────────────

@router.post("/lessons/{lesson_id}/bookmark", status_code=200)
async def toggle_bookmark(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Toggle a bookmark on a lesson; creates it if absent, removes it if present."""
    bookmarked = await service.toggle_bookmark(db, current_user.id, lesson_id)
    return ok(BookmarkToggleOut(bookmarked=bookmarked).model_dump())


@router.get("/users/me/bookmarks")
async def list_bookmarks(
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """List all of the authenticated student's bookmarks with lesson and course context."""
    bookmarks, total = await service.list_bookmarks(db, current_user.id, skip, limit)
    return ok(
        [BookmarkListItem.model_validate(b).model_dump() for b in bookmarks],
        meta={"total": total, "skip": skip, "limit": limit},
    )
