"""Integration tests for quiz AI feedback — Sprint 7B."""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import create_access_token, hash_password
from app.db.models.ai import AIUsageBudget
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.quiz import Quiz, QuizFeedback, QuizQuestion, QuizSubmission
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


async def _make_course(db: AsyncSession, created_by: uuid.UUID) -> Course:
    course = Course(
        slug=f"fb-course-{uuid.uuid4().hex[:8]}",
        title="Feedback Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _make_lesson(db: AsyncSession, course: Course) -> Lesson:
    chapter = Chapter(course_id=course.id, title="Ch 1", position=1)
    db.add(chapter)
    await db.flush()
    lesson = Lesson(
        chapter_id=chapter.id, title="L 1", position=1, type="video", is_free_preview=False
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_quiz(db: AsyncSession, lesson_id: uuid.UUID) -> Quiz:
    quiz = Quiz(lesson_id=lesson_id, title="AI Feedback Quiz", max_attempts=3)
    db.add(quiz)
    await db.flush()
    db.add(
        QuizQuestion(
            quiz_id=quiz.id,
            position=1,
            kind="single_choice",
            stem="What is the capital of France?",
            options=[{"id": "a", "text": "Paris"}, {"id": "b", "text": "London"}],
            correct_answers=["a"],
            points=1,
        )
    )
    await db.commit()
    result = await db.execute(
        select(Quiz).where(Quiz.id == quiz.id).options(selectinload(Quiz.questions))
    )
    return result.scalar_one()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _mock_llm_response(text: str = "Good job!") -> MagicMock:
    resp = MagicMock()
    resp.choices[0].message.content = json.dumps([{"feedback": text}])
    resp.usage.prompt_tokens = 20
    resp.usage.completion_tokens = 10
    return resp


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_quiz_enqueues_feedback_task(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Submitting a quiz fires generate_quiz_feedback.delay when AI is enabled."""
    admin, _ = await _make_user(db, f"adm-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    lesson = await _make_lesson(db, course)
    quiz = await _make_quiz(db, lesson.id)

    with patch("app.modules.ai.tasks.generate_quiz_feedback.delay") as mock_delay:
        resp = await client.post(
            f"/api/v1/quizzes/{quiz.id}/submissions",
            json={"answers": {str(quiz.questions[0].id): ["a"]}},
            headers=_auth(s_token),
        )

    assert resp.status_code == 201
    mock_delay.assert_called_once()
    # Argument is the string submission UUID
    called_id = mock_delay.call_args[0][0]
    assert uuid.UUID(called_id)  # valid UUID


@pytest.mark.asyncio
async def test_submit_quiz_ai_disabled_no_task(
    client: AsyncClient, db: AsyncSession
) -> None:
    """When ai_enabled=False for the course, the feedback task is not enqueued."""
    admin, _ = await _make_user(db, f"adm-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    lesson = await _make_lesson(db, course)
    quiz = await _make_quiz(db, lesson.id)

    # Disable AI for the course
    db.add(AIUsageBudget(course_id=course.id, ai_enabled=False))
    await db.commit()

    with patch("app.modules.ai.tasks.generate_quiz_feedback.delay") as mock_delay:
        resp = await client.post(
            f"/api/v1/quizzes/{quiz.id}/submissions",
            json={"answers": {str(quiz.questions[0].id): ["a"]}},
            headers=_auth(s_token),
        )

    assert resp.status_code == 201
    mock_delay.assert_not_called()


@pytest.mark.asyncio
async def test_feedback_visible_in_submission_after_task(
    client: AsyncClient, db: AsyncSession
) -> None:
    """After the task runs, per-question feedback appears in GET /submissions/{id}."""
    admin, _ = await _make_user(db, f"adm-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    lesson = await _make_lesson(db, course)
    quiz = await _make_quiz(db, lesson.id)

    # Submit quiz with wrong answer so the task has something to give feedback on
    with patch("app.modules.ai.tasks.generate_quiz_feedback.delay"):
        resp = await client.post(
            f"/api/v1/quizzes/{quiz.id}/submissions",
            json={"answers": {str(quiz.questions[0].id): ["b"]}},
            headers=_auth(s_token),
        )
    assert resp.status_code == 201
    submission_id = resp.json()["data"]["id"]

    # Run the task directly with a mocked LLM
    with (
        patch("litellm.completion", return_value=_mock_llm_response("Paris is correct!")),
        patch("app.modules.ai.tasks.log_ai_usage.delay"),
    ):
        from app.modules.ai.tasks import generate_quiz_feedback
        generate_quiz_feedback.apply(args=[submission_id])

    # Fetch the submission — feedback should now be present
    resp = await client.get(
        f"/api/v1/quizzes/submissions/{submission_id}", headers=_auth(s_token)
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["ai_feedback"]) == 1
    assert data["ai_feedback"][0]["feedback_text"] == "Paris is correct!"
    assert data["ai_feedback"][0]["question_id"] == str(quiz.questions[0].id)


@pytest.mark.asyncio
async def test_submit_response_has_empty_feedback_list(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The submit response includes ai_feedback as an empty list (task not yet run)."""
    admin, _ = await _make_user(db, f"adm-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    lesson = await _make_lesson(db, course)
    quiz = await _make_quiz(db, lesson.id)

    with patch("app.modules.ai.tasks.generate_quiz_feedback.delay"):
        resp = await client.post(
            f"/api/v1/quizzes/{quiz.id}/submissions",
            json={"answers": {str(quiz.questions[0].id): ["a"]}},
            headers=_auth(s_token),
        )

    assert resp.status_code == 201
    assert resp.json()["data"]["ai_feedback"] == []


@pytest.mark.asyncio
async def test_feedback_visible_in_list_submissions(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /quizzes/{id}/submissions includes ai_feedback after the task runs."""
    admin, _ = await _make_user(db, f"adm-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, s_token = await _make_user(db, f"stu-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    lesson = await _make_lesson(db, course)
    quiz = await _make_quiz(db, lesson.id)

    with patch("app.modules.ai.tasks.generate_quiz_feedback.delay"):
        resp = await client.post(
            f"/api/v1/quizzes/{quiz.id}/submissions",
            json={"answers": {str(quiz.questions[0].id): ["b"]}},
            headers=_auth(s_token),
        )
    submission_id = resp.json()["data"]["id"]

    with (
        patch("litellm.completion", return_value=_mock_llm_response("Nice try!")),
        patch("app.modules.ai.tasks.log_ai_usage.delay"),
    ):
        from app.modules.ai.tasks import generate_quiz_feedback
        generate_quiz_feedback.apply(args=[submission_id])

    resp = await client.get(
        f"/api/v1/quizzes/{quiz.id}/submissions", headers=_auth(s_token)
    )
    assert resp.status_code == 200
    submissions = resp.json()["data"]
    assert len(submissions) == 1
    assert len(submissions[0]["ai_feedback"]) == 1
    assert submissions[0]["ai_feedback"][0]["feedback_text"] == "Nice try!"
