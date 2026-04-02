"""Integration tests for quiz creation, retrieval, and submission endpoints."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import create_access_token, hash_password
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.quiz import Quiz, QuizQuestion
from app.db.models.user import User, UserProfile

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
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name=email.split("@")[0]))
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_lesson(db: AsyncSession, created_by: uuid.UUID) -> Lesson:
    course = Course(
        slug=f"course-{uuid.uuid4().hex[:8]}",
        title="Test Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.flush()
    chapter = Chapter(course_id=course.id, title="Chapter 1", position=1)
    db.add(chapter)
    await db.flush()
    lesson = Lesson(
        chapter_id=chapter.id,
        title="Lesson 1",
        position=1,
        type="video",
        is_free_preview=False,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_quiz(db: AsyncSession, lesson_id: uuid.UUID, max_attempts: int = 3) -> Quiz:
    quiz = Quiz(
        lesson_id=lesson_id,
        title="Test Quiz",
        max_attempts=max_attempts,
    )
    db.add(quiz)
    await db.flush()
    db.add(
        QuizQuestion(
            quiz_id=quiz.id,
            position=1,
            kind="single_choice",
            stem="What is 2+2?",
            options=[{"id": "a", "text": "3"}, {"id": "b", "text": "4"}],
            correct_answers=["b"],
            points=1,
        )
    )
    await db.commit()
    # Eagerly load questions so the relationship is accessible outside the session.
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Quiz).where(Quiz.id == quiz.id).options(selectinload(Quiz.questions))
    )
    return result.scalar_one()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_quiz_admin_ok(client: AsyncClient, db: AsyncSession) -> None:
    """Admin can create a quiz with questions."""
    admin, token = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    lesson = await _make_lesson(db, admin.id)

    payload = {
        "lesson_id": str(lesson.id),
        "title": "Sprint Quiz",
        "max_attempts": 2,
        "questions": [
            {
                "position": 1,
                "kind": "single_choice",
                "stem": "Pick one",
                "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "correct_answers": ["a"],
                "points": 1,
            }
        ],
    }
    resp = await client.post("/api/v1/admin/quizzes", json=payload, headers=_auth(token))
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["title"] == "Sprint Quiz"
    assert len(data["questions"]) == 1
    # Answers must be masked on creation response
    assert data["questions"][0]["correct_answers"] == []


@pytest.mark.asyncio
async def test_create_quiz_student_forbidden(client: AsyncClient, db: AsyncSession) -> None:
    student, token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    payload = {
        "lesson_id": str(uuid.uuid4()),
        "title": "Bad",
        "questions": [
            {
                "position": 1,
                "kind": "single_choice",
                "stem": "?",
                "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "correct_answers": ["a"],
            }
        ],
    }
    resp = await client.post("/api/v1/admin/quizzes", json=payload, headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_quiz_masks_answers(client: AsyncClient, db: AsyncSession) -> None:
    """GET /quizzes/{id} returns questions with correct_answers masked."""
    admin, a_token = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id)

    resp = await client.get(f"/api/v1/quizzes/{quiz.id}", headers=_auth(s_token))
    assert resp.status_code == 200
    questions = resp.json()["data"]["questions"]
    assert len(questions) == 1
    assert questions[0]["correct_answers"] == []


@pytest.mark.asyncio
async def test_submit_quiz_pass(client: AsyncClient, db: AsyncSession) -> None:
    """Submitting all correct answers produces passed=True and score==max_score."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id)

    resp = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        json={"answers": {str(quiz.questions[0].id): ["b"]}},
        headers=_auth(s_token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["passed"] is True
    assert data["score"] == data["max_score"]


@pytest.mark.asyncio
async def test_submit_quiz_fail(client: AsyncClient, db: AsyncSession) -> None:
    """Submitting wrong answers produces passed=False."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id)

    # Get the question ID from the DB
    from sqlalchemy import select

    from app.db.models.quiz import QuizQuestion as QQ
    result = await db.execute(select(QQ).where(QQ.quiz_id == quiz.id))
    q = result.scalar_one()

    resp = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        json={"answers": {str(q.id): ["a"]}},  # "a" is wrong; correct is "b"
        headers=_auth(s_token),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["passed"] is False
    assert data["score"] == 0


@pytest.mark.asyncio
async def test_answers_revealed_after_all_attempts(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Correct answers are revealed in the response once all attempts are used."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id, max_attempts=1)

    from sqlalchemy import select

    from app.db.models.quiz import QuizQuestion as QQ
    result = await db.execute(select(QQ).where(QQ.quiz_id == quiz.id))
    q = result.scalar_one()

    resp = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit",
        json={"answers": {str(q.id): ["a"]}},
        headers=_auth(s_token),
    )
    assert resp.status_code == 201
    questions = resp.json()["data"]["questions"]
    # max_attempts=1, so this was the final attempt — answers must be revealed
    assert questions[0]["correct_answers"] == ["b"]


@pytest.mark.asyncio
async def test_max_attempts_exceeded(client: AsyncClient, db: AsyncSession) -> None:
    """Submitting beyond max_attempts returns 409 MAX_ATTEMPTS_EXCEEDED."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id, max_attempts=1)

    from sqlalchemy import select

    from app.db.models.quiz import QuizQuestion as QQ
    result = await db.execute(select(QQ).where(QQ.quiz_id == quiz.id))
    q = result.scalar_one()

    payload = {"answers": {str(q.id): ["a"]}}
    headers = _auth(s_token)
    # First attempt — allowed
    await client.post(f"/api/v1/quizzes/{quiz.id}/submit", json=payload, headers=headers)
    # Second attempt — should be rejected
    resp = await client.post(
        f"/api/v1/quizzes/{quiz.id}/submit", json=payload, headers=headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "MAX_ATTEMPTS_EXCEEDED"


@pytest.mark.asyncio
async def test_list_submissions(client: AsyncClient, db: AsyncSession) -> None:
    """GET /quizzes/{id}/submissions returns all attempts for the student."""
    admin, _ = await _make_user(db, f"admin-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    lesson = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id, max_attempts=3)

    from sqlalchemy import select

    from app.db.models.quiz import QuizQuestion as QQ
    result = await db.execute(select(QQ).where(QQ.quiz_id == quiz.id))
    q = result.scalar_one()

    headers = _auth(s_token)
    payload = {"answers": {str(q.id): ["a"]}}
    # Submit twice
    await client.post(f"/api/v1/quizzes/{quiz.id}/submit", json=payload, headers=headers)
    await client.post(f"/api/v1/quizzes/{quiz.id}/submit", json=payload, headers=headers)

    resp = await client.get(f"/api/v1/quizzes/{quiz.id}/submissions", headers=headers)
    assert resp.status_code == 200
    submissions = resp.json()["data"]
    assert len(submissions) == 2
    assert submissions[0]["attempt_number"] == 1
    assert submissions[1]["attempt_number"] == 2
