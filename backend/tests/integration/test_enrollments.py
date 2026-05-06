"""Integration tests for enrollment, progress, notes, and bookmark endpoints."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.user import User


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession, email: str, role: str = "student"
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass123"),
        role=role,
        email_verified=True,
        display_name=email.split("@")[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_course(
    db: AsyncSession,
    created_by: uuid.UUID,
    status: str = "published",
    price_cents: int = 0,
) -> Course:
    course = Course(
        slug=f"course-{uuid.uuid4().hex[:8]}",
        title="Test Course",
        level="beginner",
        language="en",
        price_cents=price_cents,
        currency="USD",
        status=status,
        created_by=created_by,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _make_chapter(db: AsyncSession, course_id: uuid.UUID, position: int = 1) -> Chapter:
    chapter = Chapter(course_id=course_id, title=f"Chapter {position}", position=position)
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


async def _make_lesson(db: AsyncSession, chapter_id: uuid.UUID, position: int = 1) -> Lesson:
    lesson = Lesson(
        chapter_id=chapter_id,
        title=f"Lesson {position}",
        type="text",
        position=position,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_enrollment(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    status: str = "active",
) -> Enrollment:
    enrollment = Enrollment(user_id=user_id, course_id=course_id, status=status)
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


# ── Enroll ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enroll_in_free_published_course(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-enroll-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-enroll-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)

    resp = await client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["course_id"] == str(course.id)
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_enroll_duplicate_returns_409(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-dup-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-dup-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    await _make_enrollment(db, student.id, course.id)

    resp = await client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALREADY_ENROLLED"


@pytest.mark.asyncio
async def test_enroll_draft_course_returns_422(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-draft-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-draft-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id, status="draft")

    resp = await client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "COURSE_NOT_ENROLLABLE"


@pytest.mark.asyncio
async def test_enroll_paid_course_returns_422(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-paid-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-paid-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id, price_cents=999)

    resp = await client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reenroll_after_unenroll_restores_record(client: AsyncClient, db: AsyncSession) -> None:
    """Re-enrolling an unenrolled student restores the existing row, not a new one."""
    admin, _ = await _make_user(db, f"admin-re-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-re-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    enrollment = await _make_enrollment(db, student.id, course.id, status="unenrolled")
    original_id = enrollment.id

    resp = await client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["id"] == str(original_id)
    assert resp.json()["data"]["status"] == "active"


# ── Unenroll ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unenroll_sets_status_unenrolled(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-un-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-un-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    enrollment = await _make_enrollment(db, student.id, course.id)

    resp = await client.delete(
        f"/api/v1/enrollments/{enrollment.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    await db.refresh(enrollment)
    assert enrollment.status == "unenrolled"


@pytest.mark.asyncio
async def test_unenroll_another_users_enrollment_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, f"admin-unauth-{uuid.uuid4().hex[:6]}@example.com", "admin")
    owner, _ = await _make_user(db, f"owner-unauth-{uuid.uuid4().hex[:6]}@example.com")
    attacker, attacker_token = await _make_user(db, f"attacker-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    enrollment = await _make_enrollment(db, owner.id, course.id)

    resp = await client.delete(
        f"/api/v1/enrollments/{enrollment.id}",
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert resp.status_code == 404


# ── Progress ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_progress_creates_record(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-prog-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-prog-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    await _make_enrollment(db, student.id, course.id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/progress",
        json={"status": "in_progress", "watch_seconds": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "in_progress"
    assert data["watch_seconds"] == 30


@pytest.mark.asyncio
async def test_progress_idempotent_no_duplicate_rows(client: AsyncClient, db: AsyncSession) -> None:
    """Multiple POST calls to /progress for the same lesson must not create duplicate rows."""
    admin, _ = await _make_user(db, f"admin-idem-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-idem-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    await _make_enrollment(db, student.id, course.id)

    for _ in range(3):
        resp = await client.post(
            f"/api/v1/lessons/{lesson.id}/progress",
            json={"status": "in_progress", "watch_seconds": 60},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    from sqlalchemy import select, func
    count = await db.scalar(
        select(func.count(LessonProgress.id)).where(
            LessonProgress.user_id == student.id,
            LessonProgress.lesson_id == lesson.id,
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_progress_status_does_not_regress(client: AsyncClient, db: AsyncSession) -> None:
    """Sending a lower-rank status must not roll back a completed lesson."""
    admin, _ = await _make_user(db, f"admin-reg-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-reg-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    await _make_enrollment(db, student.id, course.id)

    await client.post(
        f"/api/v1/lessons/{lesson.id}/progress",
        json={"status": "completed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/progress",
        json={"status": "in_progress"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"


@pytest.mark.asyncio
async def test_non_enrolled_student_cannot_save_progress(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, f"admin-noenr-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-noenr-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    # No enrollment created

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/progress",
        json={"status": "in_progress"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NOT_ENROLLED"


@pytest.mark.asyncio
async def test_enroll_complete_lessons_updates_course_progress(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Completing all lessons in a course updates progress_pct to 100 and sets enrollment completed."""
    admin, _ = await _make_user(db, f"admin-full-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-full-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson1 = await _make_lesson(db, chapter.id, position=1)
    lesson2 = await _make_lesson(db, chapter.id, position=2)
    enrollment = await _make_enrollment(db, student.id, course.id)

    for lesson in (lesson1, lesson2):
        resp = await client.post(
            f"/api/v1/lessons/{lesson.id}/progress",
            json={"status": "completed"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    resp = await client.get(
        f"/api/v1/courses/{course.id}/progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["progress_pct"] == 100.0
    assert data["completed_lessons"] == 2
    assert data["total_lessons"] == 2

    await db.refresh(enrollment)
    assert enrollment.status == "completed"
    assert enrollment.completed_at is not None


@pytest.mark.asyncio
async def test_unenroll_reenroll_preserves_progress(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Re-enrolling after unenrolling must not erase prior lesson progress."""
    admin, _ = await _make_user(db, f"admin-pres-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-pres-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    enrollment = await _make_enrollment(db, student.id, course.id)

    # Mark the lesson complete
    await client.post(
        f"/api/v1/lessons/{lesson.id}/progress",
        json={"status": "completed"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Unenroll
    await client.delete(
        f"/api/v1/enrollments/{enrollment.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Re-enroll
    resp = await client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    # Prior progress must still be there
    from sqlalchemy import select
    progress = await db.scalar(
        select(LessonProgress).where(
            LessonProgress.user_id == student.id,
            LessonProgress.lesson_id == lesson.id,
        )
    )
    assert progress is not None
    assert progress.status == "completed"


# ── Notes ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_note_creates_then_updates(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-note-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-note-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    await _make_enrollment(db, student.id, course.id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"content": "first note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    note_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"content": "updated note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == note_id
    assert resp.json()["data"]["content"] == "updated note"


@pytest.mark.asyncio
async def test_get_note_returns_404_when_absent(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-notenf-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-notenf-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    await _make_enrollment(db, student.id, course.id)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/notes",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOTE_NOT_FOUND"


@pytest.mark.asyncio
async def test_non_enrolled_cannot_create_note(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, f"admin-noteauth-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-noteauth-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/notes",
        json={"content": "sneaky note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── Bookmarks ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bookmark_put_and_delete_are_idempotent(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, f"admin-bm-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-bm-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    await _make_enrollment(db, student.id, course.id)

    resp = await client.put(
        f"/api/v1/lessons/{lesson.id}/bookmark",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["bookmarked"] is True

    resp = await client.put(
        f"/api/v1/lessons/{lesson.id}/bookmark",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["bookmarked"] is True

    resp = await client.delete(
        f"/api/v1/lessons/{lesson.id}/bookmark",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["bookmarked"] is False

    resp = await client.delete(
        f"/api/v1/lessons/{lesson.id}/bookmark",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["bookmarked"] is False


@pytest.mark.asyncio
async def test_list_bookmarks_returns_lesson_and_course_context(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, _ = await _make_user(db, f"admin-bmlist-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, token = await _make_user(db, f"student-bmlist-{uuid.uuid4().hex[:6]}@example.com")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    await _make_enrollment(db, student.id, course.id)

    await client.put(
        f"/api/v1/lessons/{lesson.id}/bookmark",
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(
        "/api/v1/users/me/bookmarks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 1
    assert items[0]["lesson"]["id"] == str(lesson.id)
    assert items[0]["lesson"]["chapter"]["course"]["id"] == str(course.id)
