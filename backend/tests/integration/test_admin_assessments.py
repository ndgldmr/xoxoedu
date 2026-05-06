"""Integration tests for admin quiz read/update and assignment read/update endpoints.

Covers:
  GET  /admin/lessons/{lesson_id}/quiz          — fetch quiz with answers revealed
  PATCH /admin/quizzes/{quiz_id}                — full-replacement quiz update
  GET  /admin/lessons/{lesson_id}/assignment    — fetch assignment
  PATCH /admin/assignments/{assignment_id}      — partial assignment update
  GET  /admin/submissions/{submission_id}       — submission detail with download URL
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.assignment import Assignment, AssignmentSubmission
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.quiz import Quiz, QuizQuestion
from app.db.models.user import User

_FAKE_DOWNLOAD_URL = "https://r2.example.com/fake-download"


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(db: AsyncSession, email: str, role: str = "student") -> tuple[User, str]:
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


async def _make_lesson(db: AsyncSession, created_by: uuid.UUID, lesson_type: str = "quiz") -> tuple[Lesson, Course]:
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
        type=lesson_type,
        is_free_preview=False,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    await db.refresh(course)
    return lesson, course


async def _make_quiz(db: AsyncSession, lesson_id: uuid.UUID) -> Quiz:
    quiz = Quiz(
        lesson_id=lesson_id,
        title="Original Quiz",
        description="Original description",
        max_attempts=3,
        time_limit_minutes=None,
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
    await db.refresh(quiz)
    return quiz


async def _make_assignment(db: AsyncSession, lesson_id: uuid.UUID) -> Assignment:
    assignment = Assignment(
        lesson_id=lesson_id,
        title="Original Assignment",
        instructions="Original instructions.",
        max_file_size_bytes=10_485_760,
        allowed_extensions=["pdf"],
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def _make_confirmed_submission(
    db: AsyncSession, user_id: uuid.UUID, assignment: Assignment
) -> AssignmentSubmission:
    sub = AssignmentSubmission(
        user_id=user_id,
        assignment_id=assignment.id,
        file_key="assignments/x/report.pdf",
        file_name="report.pdf",
        file_size=2048,
        mime_type="application/pdf",
        scan_status="clean",
        submitted_at=datetime.now(UTC),
        attempt_number=1,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Quiz admin GET ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_quiz_admin_reveals_correct_answers(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/lessons/{id}/quiz returns questions with correct_answers populated."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id)

    resp = await client.get(
        f"/api/v1/admin/lessons/{lesson.id}/quiz",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(quiz.id)
    assert data["title"] == "Original Quiz"
    # Admin endpoint must reveal correct answers
    assert data["questions"][0]["correct_answers"] == ["b"]


@pytest.mark.asyncio
async def test_get_quiz_admin_404_when_no_quiz(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/lessons/{id}/quiz returns 404 when no quiz is attached."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id)

    resp = await client.get(
        f"/api/v1/admin/lessons/{lesson.id}/quiz",
        headers=_auth(token),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "QUIZ_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_quiz_admin_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Student token cannot access the admin quiz read endpoint."""
    admin, _ = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, s_token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    lesson, _ = await _make_lesson(db, admin.id)
    await _make_quiz(db, lesson.id)

    resp = await client.get(
        f"/api/v1/admin/lessons/{lesson.id}/quiz",
        headers=_auth(s_token),
    )
    assert resp.status_code == 403


# ── Quiz admin PATCH ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_quiz_admin_updates_metadata(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH /admin/quizzes/{id} updates quiz title, description, and settings."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id)

    payload = {
        "title": "Updated Quiz",
        "description": "Updated description",
        "max_attempts": 2,
        "time_limit_minutes": 15,
        "questions": [
            {
                "position": 1,
                "kind": "single_choice",
                "stem": "What is 2+2?",
                "options": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}],
                "correct_answers": ["b"],
                "points": 1,
            }
        ],
    }
    resp = await client.patch(
        f"/api/v1/admin/quizzes/{quiz.id}",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["title"] == "Updated Quiz"
    assert data["description"] == "Updated description"
    assert data["max_attempts"] == 2
    assert data["time_limit_minutes"] == 15


@pytest.mark.asyncio
async def test_patch_quiz_admin_replaces_questions(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH replaces the entire question set; old questions are removed."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id)
    quiz = await _make_quiz(db, lesson.id)  # starts with 1 question

    payload = {
        "title": "Quiz with two questions",
        "description": None,
        "max_attempts": 3,
        "time_limit_minutes": None,
        "questions": [
            {
                "position": 1,
                "kind": "single_choice",
                "stem": "Question one?",
                "options": [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}],
                "correct_answers": ["a"],
                "points": 1,
            },
            {
                "position": 2,
                "kind": "multi_choice",
                "stem": "Select all correct.",
                "options": [
                    {"id": "x", "text": "X"},
                    {"id": "y", "text": "Y"},
                    {"id": "z", "text": "Z"},
                ],
                "correct_answers": ["x", "y"],
                "points": 2,
            },
        ],
    }
    resp = await client.patch(
        f"/api/v1/admin/quizzes/{quiz.id}",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200
    questions = resp.json()["data"]["questions"]
    assert len(questions) == 2
    # Correct answers must be revealed in the admin update response
    assert questions[0]["correct_answers"] == ["a"]
    assert questions[1]["correct_answers"] == ["x", "y"]


@pytest.mark.asyncio
async def test_patch_quiz_admin_clears_time_limit(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Setting time_limit_minutes to null removes the time limit."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id)

    # Create quiz with a time limit
    quiz = Quiz(
        lesson_id=lesson.id,
        title="Timed Quiz",
        max_attempts=2,
        time_limit_minutes=30,
    )
    db.add(quiz)
    await db.flush()
    db.add(
        QuizQuestion(
            quiz_id=quiz.id,
            position=1,
            kind="single_choice",
            stem="Q?",
            options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            correct_answers=["a"],
            points=1,
        )
    )
    await db.commit()
    await db.refresh(quiz)

    payload = {
        "title": "Timed Quiz",
        "description": None,
        "max_attempts": 2,
        "time_limit_minutes": None,
        "questions": [
            {
                "position": 1,
                "kind": "single_choice",
                "stem": "Q?",
                "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "correct_answers": ["a"],
                "points": 1,
            }
        ],
    }
    resp = await client.patch(
        f"/api/v1/admin/quizzes/{quiz.id}",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["time_limit_minutes"] is None


@pytest.mark.asyncio
async def test_patch_quiz_admin_404_on_unknown_quiz(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH /admin/quizzes/{id} returns 404 for a non-existent quiz."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    payload = {
        "title": "x",
        "description": None,
        "max_attempts": 1,
        "time_limit_minutes": None,
        "questions": [
            {
                "position": 1,
                "kind": "single_choice",
                "stem": "?",
                "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "correct_answers": ["a"],
                "points": 1,
            }
        ],
    }
    resp = await client.patch(
        f"/api/v1/admin/quizzes/{uuid.uuid4()}",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "QUIZ_NOT_FOUND"


@pytest.mark.asyncio
async def test_patch_quiz_admin_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Student token is rejected by PATCH /admin/quizzes/{id}."""
    _, s_token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    payload = {
        "title": "x",
        "description": None,
        "max_attempts": 1,
        "time_limit_minutes": None,
        "questions": [
            {
                "position": 1,
                "kind": "single_choice",
                "stem": "?",
                "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "correct_answers": ["a"],
                "points": 1,
            }
        ],
    }
    resp = await client.patch(
        f"/api/v1/admin/quizzes/{uuid.uuid4()}",
        json=payload,
        headers=_auth(s_token),
    )
    assert resp.status_code == 403


# ── Assignment admin GET ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_assignment_admin_ok(client: AsyncClient, db: AsyncSession) -> None:
    """GET /admin/lessons/{id}/assignment returns the assignment record."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id, lesson_type="assignment")
    assignment = await _make_assignment(db, lesson.id)

    resp = await client.get(
        f"/api/v1/admin/lessons/{lesson.id}/assignment",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(assignment.id)
    assert data["title"] == "Original Assignment"
    assert data["allowed_extensions"] == ["pdf"]


@pytest.mark.asyncio
async def test_get_assignment_admin_404_when_no_assignment(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/lessons/{id}/assignment returns 404 when no assignment is attached."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id, lesson_type="assignment")

    resp = await client.get(
        f"/api/v1/admin/lessons/{lesson.id}/assignment",
        headers=_auth(token),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ASSIGNMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_assignment_admin_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Student token cannot access the admin assignment read endpoint."""
    admin, _ = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    _, s_token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    lesson, _ = await _make_lesson(db, admin.id, lesson_type="assignment")
    await _make_assignment(db, lesson.id)

    resp = await client.get(
        f"/api/v1/admin/lessons/{lesson.id}/assignment",
        headers=_auth(s_token),
    )
    assert resp.status_code == 403


# ── Assignment admin PATCH ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_assignment_admin_updates_fields(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH /admin/assignments/{id} updates provided fields and leaves others intact."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id, lesson_type="assignment")
    assignment = await _make_assignment(db, lesson.id)

    resp = await client.patch(
        f"/api/v1/admin/assignments/{assignment.id}",
        json={"title": "Updated Assignment", "instructions": "New instructions."},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["title"] == "Updated Assignment"
    assert data["instructions"] == "New instructions."
    # Unset fields should retain their original values
    assert data["allowed_extensions"] == ["pdf"]
    assert data["max_file_size_bytes"] == 10_485_760


@pytest.mark.asyncio
async def test_patch_assignment_admin_updates_extensions(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH can replace the allowed_extensions list."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id, lesson_type="assignment")
    assignment = await _make_assignment(db, lesson.id)

    resp = await client.patch(
        f"/api/v1/admin/assignments/{assignment.id}",
        json={"allowed_extensions": ["docx", "zip"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert sorted(resp.json()["data"]["allowed_extensions"]) == ["docx", "zip"]


@pytest.mark.asyncio
async def test_patch_assignment_admin_clears_extensions(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Sending allowed_extensions=[] removes all extension restrictions."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    lesson, _ = await _make_lesson(db, admin.id, lesson_type="assignment")
    assignment = await _make_assignment(db, lesson.id)

    resp = await client.patch(
        f"/api/v1/admin/assignments/{assignment.id}",
        json={"allowed_extensions": []},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["allowed_extensions"] == []


@pytest.mark.asyncio
async def test_patch_assignment_admin_404_on_unknown(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH /admin/assignments/{id} returns 404 for a non-existent assignment."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    resp = await client.patch(
        f"/api/v1/admin/assignments/{uuid.uuid4()}",
        json={"title": "x"},
        headers=_auth(token),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ASSIGNMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_patch_assignment_admin_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Student token is rejected by PATCH /admin/assignments/{id}."""
    _, s_token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    resp = await client.patch(
        f"/api/v1/admin/assignments/{uuid.uuid4()}",
        json={"title": "x"},
        headers=_auth(s_token),
    )
    assert resp.status_code == 403


# ── Submission detail GET ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_submission_detail_admin_ok(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/submissions/{id} returns all fields including a download URL."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    lesson, _ = await _make_lesson(db, admin.id, lesson_type="assignment")
    assignment = await _make_assignment(db, lesson.id)
    sub = await _make_confirmed_submission(db, student.id, assignment)

    with patch(
        "app.modules.admin.service.generate_presigned_get",
        return_value=_FAKE_DOWNLOAD_URL,
    ):
        resp = await client.get(
            f"/api/v1/admin/submissions/{sub.id}",
            headers=_auth(token),
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == str(sub.id)
    assert data["file_name"] == "report.pdf"
    assert data["download_url"] == _FAKE_DOWNLOAD_URL
    assert data["assignment_title"] == "Original Assignment"
    assert data["lesson_title"] == "Lesson 1"
    assert data["user_email"] == student.email


@pytest.mark.asyncio
async def test_get_submission_detail_download_url_none_on_storage_failure(
    client: AsyncClient, db: AsyncSession
) -> None:
    """download_url is None when the R2 presign call raises an exception."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    lesson, _ = await _make_lesson(db, admin.id, lesson_type="assignment")
    assignment = await _make_assignment(db, lesson.id)
    sub = await _make_confirmed_submission(db, student.id, assignment)

    with patch(
        "app.modules.admin.service.generate_presigned_get",
        side_effect=RuntimeError("R2 unavailable"),
    ):
        resp = await client.get(
            f"/api/v1/admin/submissions/{sub.id}",
            headers=_auth(token),
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["download_url"] is None


@pytest.mark.asyncio
async def test_get_submission_detail_404_on_unknown(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/submissions/{id} returns 404 for a non-existent submission."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    resp = await client.get(
        f"/api/v1/admin/submissions/{uuid.uuid4()}",
        headers=_auth(token),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ASSIGNMENT_SUBMISSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_submission_detail_requires_admin(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Student token cannot access the submission detail endpoint."""
    _, s_token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    resp = await client.get(
        f"/api/v1/admin/submissions/{uuid.uuid4()}",
        headers=_auth(s_token),
    )
    assert resp.status_code == 403


# ── Submission list now includes assignment/lesson titles ──────────────────────

@pytest.mark.asyncio
async def test_list_submissions_includes_titles(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/courses/{id}/submissions enriches rows with assignment and lesson titles."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    lesson, course = await _make_lesson(db, admin.id, lesson_type="assignment")
    assignment = await _make_assignment(db, lesson.id)
    await _make_confirmed_submission(db, student.id, assignment)

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/submissions",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["assignment_title"] == "Original Assignment"
    assert data[0]["lesson_title"] == "Lesson 1"
