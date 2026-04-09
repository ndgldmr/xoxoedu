"""Integration tests for admin grading endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.assignment import Assignment, AssignmentSubmission
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.user import User, UserProfile

_FAKE_URL = "https://r2.example.com/fake"


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


async def _make_assignment(db: AsyncSession, admin_id: uuid.UUID) -> Assignment:
    course = Course(
        slug=f"c-{uuid.uuid4().hex[:8]}",
        title="Course",
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
    lesson = Lesson(chapter_id=chapter.id, title="L 1", position=1, type="assignment")
    db.add(lesson)
    await db.flush()
    assignment = Assignment(
        lesson_id=lesson.id,
        title="Final Project",
        instructions="Submit a report.",
        allowed_extensions=["pdf"],
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    await db.refresh(course)
    return assignment, course


async def _submit(
    db: AsyncSession, user_id: uuid.UUID, assignment: Assignment
) -> AssignmentSubmission:
    sub = AssignmentSubmission(
        user_id=user_id,
        assignment_id=assignment.id,
        file_key="assignments/x/report.pdf",
        file_name="report.pdf",
        file_size=1024,
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


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_submissions_empty(client: AsyncClient, db: AsyncSession) -> None:
    """GET /admin/courses/{id}/submissions returns empty list when no submissions exist."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    _, course = await _make_assignment(db, admin.id)

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/submissions",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []
    assert resp.json()["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_list_submissions_returns_confirmed_only(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Only submissions with submitted_at set appear in the queue."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    assignment, course = await _make_assignment(db, admin.id)

    # Unconfirmed upload (submitted_at is None)
    unconfirmed = AssignmentSubmission(
        user_id=student.id,
        assignment_id=assignment.id,
        file_key="k",
        file_name="f.pdf",
        file_size=100,
        mime_type="application/pdf",
        scan_status="pending",
        attempt_number=1,
    )
    db.add(unconfirmed)
    await db.commit()

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/submissions",
        headers=_auth(token),
    )
    assert resp.json()["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_list_submissions_ungraded_filter(
    client: AsyncClient, db: AsyncSession
) -> None:
    """?status=ungraded returns only submissions without a published grade."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    assignment, course = await _make_assignment(db, admin.id)
    sub = await _submit(db, student.id, assignment)

    resp = await client.get(
        f"/api/v1/admin/courses/{course.id}/submissions?status=ungraded",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == str(sub.id)
    assert data[0]["grade_published_at"] is None


@pytest.mark.asyncio
async def test_grade_submission_draft(client: AsyncClient, db: AsyncSession) -> None:
    """PATCH /admin/submissions/{id}/grade with publish=False saves a draft."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    assignment, _ = await _make_assignment(db, admin.id)
    sub = await _submit(db, student.id, assignment)

    resp = await client.patch(
        f"/api/v1/admin/submissions/{sub.id}/grade",
        json={"grade_score": 78.0, "grade_feedback": "Good effort.", "publish": False},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["grade_score"] == 78.0
    assert data["grade_feedback"] == "Good effort."
    assert data["grade_published_at"] is None


@pytest.mark.asyncio
async def test_grade_submission_published(client: AsyncClient, db: AsyncSession) -> None:
    """PATCH /admin/submissions/{id}/grade with publish=True sets grade_published_at."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    assignment, _ = await _make_assignment(db, admin.id)
    sub = await _submit(db, student.id, assignment)

    resp = await client.patch(
        f"/api/v1/admin/submissions/{sub.id}/grade",
        json={"grade_score": 92.0, "grade_feedback": "Excellent.", "publish": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["grade_score"] == 92.0
    assert data["grade_published_at"] is not None
    assert data["graded_by"] == str(admin.id)


@pytest.mark.asyncio
async def test_grade_submission_publish_twice_rejected(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Publishing a grade twice returns 409 SUBMISSION_ALREADY_GRADED."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    assignment, _ = await _make_assignment(db, admin.id)
    sub = await _submit(db, student.id, assignment)

    payload = {"grade_score": 80.0, "grade_feedback": "OK.", "publish": True}
    await client.patch(
        f"/api/v1/admin/submissions/{sub.id}/grade",
        json=payload,
        headers=_auth(token),
    )
    resp2 = await client.patch(
        f"/api/v1/admin/submissions/{sub.id}/grade",
        json=payload,
        headers=_auth(token),
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "SUBMISSION_ALREADY_GRADED"


@pytest.mark.asyncio
async def test_reopen_submission(client: AsyncClient, db: AsyncSession) -> None:
    """POST /admin/submissions/{id}/reopen sets is_reopened=True."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    assignment, _ = await _make_assignment(db, admin.id)
    sub = await _submit(db, student.id, assignment)

    resp = await client.post(
        f"/api/v1/admin/submissions/{sub.id}/reopen",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_reopened"] is True


@pytest.mark.asyncio
async def test_grade_requires_admin(client: AsyncClient, db: AsyncSession) -> None:
    """Student token cannot access grading endpoints."""
    student, token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")

    resp = await client.patch(
        f"/api/v1/admin/submissions/{uuid.uuid4()}/grade",
        json={"grade_score": 50.0, "grade_feedback": "x", "publish": False},
        headers=_auth(token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_grade_not_gradeable_if_not_confirmed(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Grading a submission whose uploaded_at is None returns 422."""
    admin, token = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    assignment, _ = await _make_assignment(db, admin.id)

    # Insert unconfirmed submission directly
    student, _ = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    sub = AssignmentSubmission(
        user_id=student.id,
        assignment_id=assignment.id,
        file_key="k",
        file_name="f.pdf",
        file_size=100,
        mime_type="application/pdf",
        scan_status="pending",
        attempt_number=1,
        # submitted_at intentionally left None
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    resp = await client.patch(
        f"/api/v1/admin/submissions/{sub.id}/grade",
        json={"grade_score": 70.0, "grade_feedback": "Try again.", "publish": False},
        headers=_auth(token),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "SUBMISSION_NOT_GRADEABLE"


@pytest.mark.asyncio
async def test_attempt_number_increments_on_reupload(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Second upload for the same student+assignment gets attempt_number=2."""
    admin, _ = await _make_user(db, f"a-{uuid.uuid4().hex[:6]}@x.com", "admin")
    student, s_token = await _make_user(db, f"s-{uuid.uuid4().hex[:6]}@x.com")
    assignment, _ = await _make_assignment(db, admin.id)

    with patch(
        "app.modules.assignments.service.generate_presigned_put",
        return_value=_FAKE_URL,
    ):
        r1 = await client.post(
            f"/api/v1/assignments/{assignment.id}/upload",
            json={"file_name": "r1.pdf", "mime_type": "application/pdf", "file_size": 100},
            headers=_auth(s_token),
        )
        r2 = await client.post(
            f"/api/v1/assignments/{assignment.id}/upload",
            json={"file_name": "r2.pdf", "mime_type": "application/pdf", "file_size": 100},
            headers=_auth(s_token),
        )

    sub1_id = r1.json()["data"]["submission_id"]
    sub2_id = r2.json()["data"]["submission_id"]

    # Confirm both uploads so we can check attempt_number via list endpoint
    with patch(
        "app.modules.assignments.service.generate_presigned_put",
        return_value=_FAKE_URL,
    ):
        await client.post(
            f"/api/v1/assignments/submissions/{sub1_id}/confirm",
            headers=_auth(s_token),
        )
        await client.post(
            f"/api/v1/assignments/submissions/{sub2_id}/confirm",
            headers=_auth(s_token),
        )

    list_resp = await client.get(
        f"/api/v1/assignments/{assignment.id}/submissions",
        headers=_auth(s_token),
    )
    submissions = list_resp.json()["data"]
    assert len(submissions) == 2
    attempt_numbers = sorted(s["attempt_number"] for s in submissions)
    assert attempt_numbers == [1, 2]
