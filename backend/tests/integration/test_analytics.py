"""Integration tests for admin analytics endpoints."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.payment import Payment
from app.db.models.quiz import Quiz, QuizQuestion, QuizSubmission
from app.db.models.user import User, UserProfile


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(db: AsyncSession, email: str, role: str = "student") -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("pass"),
        role=role,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name=email.split("@")[0]))
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_course_with_lessons(
    db: AsyncSession, admin_id: uuid.UUID, n_lessons: int = 3
) -> tuple[Course, list[Lesson]]:
    course = Course(
        slug=f"c-{uuid.uuid4().hex[:8]}",
        title=f"Course {uuid.uuid4().hex[:4]}",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=admin_id,
    )
    db.add(course)
    await db.flush()
    chapter = Chapter(course_id=course.id, title="Ch 1", position=1)
    db.add(chapter)
    await db.flush()
    lessons = []
    for i in range(1, n_lessons + 1):
        lesson = Lesson(
            chapter_id=chapter.id,
            title=f"Lesson {i}",
            position=i,
            type="text",
        )
        db.add(lesson)
        lessons.append(lesson)
    await db.commit()
    await db.refresh(course)
    for lesson in lessons:
        await db.refresh(lesson)
    return course, lessons


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_course_analytics_enrollment_counts(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Course analytics correctly counts active and completed enrollments."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    course, _ = await _make_course_with_lessons(db, admin.id)

    # 2 active enrollments
    for i in range(2):
        s, _ = await _make_user(db, f"s{i}-{uuid.uuid4().hex[:4]}@x.com")
        db.add(Enrollment(user_id=s.id, course_id=course.id, status="active"))
    # 1 completed enrollment
    sc, _ = await _make_user(db, f"sc-{uuid.uuid4().hex[:4]}@x.com")
    db.add(
        Enrollment(
            user_id=sc.id,
            course_id=course.id,
            status="completed",
            completed_at=datetime.now(UTC),
        )
    )
    await db.commit()

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/analytics",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_enrollments"] == 3
    assert data["active_enrollments"] == 2
    assert data["completed_enrollments"] == 1
    assert abs(data["completion_rate"] - (1 / 3)) < 0.01


@pytest.mark.asyncio
async def test_course_analytics_no_quiz_score_when_none(
    client: AsyncClient, db: AsyncSession
) -> None:
    """average_quiz_score is None when there are no quiz submissions."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    course, _ = await _make_course_with_lessons(db, admin.id)

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/analytics",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["average_quiz_score"] is None


@pytest.mark.asyncio
async def test_course_analytics_lesson_drop_off_ordered(
    client: AsyncClient, db: AsyncSession
) -> None:
    """lesson_drop_off is ordered by chapter/lesson position and includes all lessons."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    course, lessons = await _make_course_with_lessons(db, admin.id, n_lessons=3)

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/analytics",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    drop_off = resp.json()["data"]["lesson_drop_off"]
    assert len(drop_off) == 3
    titles = [item["lesson_title"] for item in drop_off]
    assert titles == ["Lesson 1", "Lesson 2", "Lesson 3"]


@pytest.mark.asyncio
async def test_course_analytics_lesson_completion_rate(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Lesson completion_rate reflects the proportion of enrolled students who finished it."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    course, lessons = await _make_course_with_lessons(db, admin.id, n_lessons=2)

    s1, _ = await _make_user(db, f"s1-{uuid.uuid4().hex[:4]}@x.com")
    s2, _ = await _make_user(db, f"s2-{uuid.uuid4().hex[:4]}@x.com")
    for s in [s1, s2]:
        db.add(Enrollment(user_id=s.id, course_id=course.id, status="active"))

    # s1 completes lesson 1 only
    db.add(
        LessonProgress(
            user_id=s1.id, lesson_id=lessons[0].id, status="completed",
            completed_at=datetime.now(UTC),
        )
    )
    await db.commit()

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/analytics",
        headers=_auth(token),
    )
    drop_off = resp.json()["data"]["lesson_drop_off"]
    # Lesson 1: 1 out of 2 active students = 0.5
    assert abs(drop_off[0]["completion_rate"] - 0.5) < 0.01
    assert drop_off[0]["completion_count"] == 1
    # Lesson 2: 0 completions
    assert drop_off[1]["completion_count"] == 0


@pytest.mark.asyncio
async def test_course_students_table(client: AsyncClient, db: AsyncSession) -> None:
    """GET /admin/courses/{id}/students returns a row per enrolled student."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    course, lessons = await _make_course_with_lessons(db, admin.id, n_lessons=2)

    s1, _ = await _make_user(db, f"s1-{uuid.uuid4().hex[:4]}@x.com")
    s2, _ = await _make_user(db, f"s2-{uuid.uuid4().hex[:4]}@x.com")
    for s in [s1, s2]:
        db.add(Enrollment(user_id=s.id, course_id=course.id, status="active"))

    # s1 completes both lessons
    for lesson in lessons:
        db.add(
            LessonProgress(
                user_id=s1.id, lesson_id=lesson.id, status="completed",
                completed_at=datetime.now(UTC),
            )
        )
    await db.commit()

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/students",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert resp.json()["meta"]["total"] == 2
    emails = {row["user_email"] for row in data}
    assert s1.email in emails
    assert s2.email in emails

    s1_row = next(r for r in data if r["user_email"] == s1.email)
    assert abs(s1_row["completion_pct"] - 1.0) < 0.01

    s2_row = next(r for r in data if r["user_email"] == s2.email)
    assert s2_row["completion_pct"] == 0.0


@pytest.mark.asyncio
async def test_platform_analytics_student_count(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Platform analytics counts student-role users correctly."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")

    before = (
        await client.get("/api/v1/admin/analytics/platform", headers=_auth(token))
    ).json()["data"]["total_students"]

    await _make_user(db, f"s1-{uuid.uuid4().hex[:4]}@x.com", "student")
    await _make_user(db, f"s2-{uuid.uuid4().hex[:4]}@x.com", "student")

    resp = await client.get("/api/v1/admin/analytics/platform", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["total_students"] == before + 2


@pytest.mark.asyncio
async def test_platform_analytics_revenue(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Platform analytics sums only completed payments for revenue."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    course, _ = await _make_course_with_lessons(db, admin.id)
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:4]}@x.com")

    before_resp = await client.get(
        "/api/v1/admin/analytics/platform", headers=_auth(token)
    )
    before_rev = before_resp.json()["data"]["total_revenue_cents"]

    db.add(
        Payment(
            user_id=student.id,
            course_id=course.id,
            amount_cents=4999,
            currency="usd",
            status="completed",
            provider="stripe",
        )
    )
    # pending payment should NOT count
    db.add(
        Payment(
            user_id=student.id,
            course_id=course.id,
            amount_cents=9999,
            currency="usd",
            status="pending",
            provider="stripe",
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/admin/analytics/platform", headers=_auth(token))
    assert resp.json()["data"]["total_revenue_cents"] == before_rev + 4999


@pytest.mark.asyncio
async def test_analytics_requires_admin(client: AsyncClient, db: AsyncSession) -> None:
    """Student token cannot access analytics endpoints."""
    student, token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")

    resp = await client.get(
        "/api/v1/admin/analytics/platform", headers=_auth(token)
    )
    assert resp.status_code == 403
