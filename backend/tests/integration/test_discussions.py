"""Integration tests for lesson discussion thread endpoints."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.discussion import DiscussionPost
from app.db.models.enrollment import Enrollment
from app.db.models.user import User
from app.modules.discussions.service import TOMBSTONE


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
        slug=f"disc-course-{uuid.uuid4().hex[:8]}",
        title="Discussion Test Course",
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


async def _make_chapter(db: AsyncSession, course_id: uuid.UUID) -> Chapter:
    chapter = Chapter(course_id=course_id, title="Chapter 1", position=1)
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


async def _make_lesson(db: AsyncSession, chapter_id: uuid.UUID) -> Lesson:
    lesson = Lesson(
        chapter_id=chapter_id,
        title="Lesson 1",
        type="text",
        position=1,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_enrollment(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> Enrollment:
    enrollment = Enrollment(user_id=user_id, course_id=course_id, status="active")
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def _make_post(
    db: AsyncSession,
    lesson_id: uuid.UUID,
    author_id: uuid.UUID,
    body: str = "Test post body",
    parent_id: uuid.UUID | None = None,
) -> DiscussionPost:
    post = DiscussionPost(
        lesson_id=lesson_id,
        author_id=author_id,
        body=body,
        parent_id=parent_id,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return post


async def _setup_lesson(db: AsyncSession) -> tuple[Course, Lesson, uuid.UUID]:
    """Return a published course, a lesson in it, and the admin user id."""
    admin, _ = await _make_user(db, f"disc-admin-{uuid.uuid4().hex[:6]}@example.com", "admin")
    course = await _make_course(db, admin.id)
    chapter = await _make_chapter(db, course.id)
    lesson = await _make_lesson(db, chapter.id)
    return course, lesson, admin.id


# ── POST /lessons/{id}/discussions ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrolled_student_can_create_top_level_post(
    client: AsyncClient, db: AsyncSession
) -> None:
    """An enrolled student can create a top-level discussion post."""
    course, lesson, _ = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-s1-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/discussions",
        json={"body": "Hello world"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["body"] == "Hello world"
    assert data["lesson_id"] == str(lesson.id)
    assert data["parent_id"] is None
    assert data["is_deleted"] is False
    assert data["author"]["id"] == str(student.id)
    assert data["reply_count"] == 0


@pytest.mark.asyncio
async def test_enrolled_student_can_create_reply(
    client: AsyncClient, db: AsyncSession
) -> None:
    """An enrolled student can create a reply to an existing top-level post."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-s2-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    parent = await _make_post(db, lesson.id, admin_id, "Original post")

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/discussions",
        json={"body": "Great point!", "parent_id": str(parent.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["parent_id"] == str(parent.id)
    assert data["body"] == "Great point!"


@pytest.mark.asyncio
async def test_non_enrolled_student_cannot_create_post(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student not enrolled in the course gets 403 on create."""
    course, lesson, _ = await _setup_lesson(db)
    outsider, token = await _make_user(db, f"disc-out-{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/discussions",
        json={"body": "Should be blocked"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NOT_ENROLLED"


@pytest.mark.asyncio
async def test_reply_to_nonexistent_parent_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Replying to a non-existent parent post returns 404."""
    course, lesson, _ = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-s3-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/discussions",
        json={"body": "Orphan reply", "parent_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DISCUSSION_POST_NOT_FOUND"


@pytest.mark.asyncio
async def test_reply_to_a_reply_is_rejected(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Replies to replies (depth > 1) are rejected with 403."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-s4-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)

    parent = await _make_post(db, lesson.id, admin_id, "Top-level")
    reply = await _make_post(db, lesson.id, admin_id, "Reply", parent_id=parent.id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/discussions",
        json={"body": "Nested reply", "parent_id": str(reply.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "DISCUSSION_POST_FORBIDDEN"


# ── GET /lessons/{id}/discussions ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_enrolled_student_cannot_read_thread(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student not enrolled in the course gets 403 on list."""
    course, lesson, admin_id = await _setup_lesson(db)
    await _make_post(db, lesson.id, admin_id)
    outsider, token = await _make_user(db, f"disc-ro-{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_top_level_posts_returns_newest_first(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Top-level posts are returned newest-first and include correct metadata."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-list-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)

    post_a = await _make_post(db, lesson.id, admin_id, "First post")
    post_b = await _make_post(db, lesson.id, admin_id, "Second post")
    # Add a reply to post_a so its reply_count > 0
    await _make_post(db, lesson.id, admin_id, "Reply to first", parent_id=post_a.id)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    posts = resp.json()["data"]
    ids = [p["id"] for p in posts]

    # Newest-first: post_b was created after post_a
    assert ids.index(str(post_b.id)) < ids.index(str(post_a.id))

    # post_a has one reply; post_b has none
    post_a_data = next(p for p in posts if p["id"] == str(post_a.id))
    post_b_data = next(p for p in posts if p["id"] == str(post_b.id))
    assert post_a_data["reply_count"] == 1
    assert post_b_data["reply_count"] == 0


@pytest.mark.asyncio
async def test_list_replies_returns_oldest_first(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Replies to a parent post are returned oldest-first."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-rep-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)

    parent = await _make_post(db, lesson.id, admin_id, "Parent")
    reply_a = await _make_post(db, lesson.id, admin_id, "First reply", parent_id=parent.id)
    reply_b = await _make_post(db, lesson.id, admin_id, "Second reply", parent_id=parent.id)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        params={"parent_id": str(parent.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["data"]]
    assert ids.index(str(reply_a.id)) < ids.index(str(reply_b.id))


@pytest.mark.asyncio
async def test_cursor_pagination_no_duplicates_or_skips(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Cursor pagination across two pages returns all posts with no duplicates or skips."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-page-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)

    created_ids = set()
    for i in range(5):
        p = await _make_post(db, lesson.id, admin_id, f"Post {i}")
        created_ids.add(str(p.id))

    # Page 1: limit=3
    resp1 = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        params={"limit": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    page1_ids = {p["id"] for p in body1["data"]}
    next_cursor = body1["meta"]["next_cursor"]
    assert next_cursor is not None
    assert len(page1_ids) == 3

    # Page 2: use cursor
    resp2 = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        params={"limit": 3, "cursor": next_cursor},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    page2_ids = {p["id"] for p in body2["data"]}
    assert len(page2_ids) == 2  # 5 posts total, 3 on page 1

    # No overlap
    assert page1_ids.isdisjoint(page2_ids)

    # Together they cover all created posts
    assert page1_ids | page2_ids == created_ids

    # No further pages
    assert body2["meta"]["next_cursor"] is None


# ── PATCH /discussions/{id} ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edit_own_post_succeeds(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student can edit the body of their own post."""
    course, lesson, _ = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-edit-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    post = await _make_post(db, lesson.id, student.id, "Original body")

    resp = await client.patch(
        f"/api/v1/discussions/{post.id}",
        json={"body": "Updated body"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["body"] == "Updated body"
    assert data["edited_at"] is not None
    assert data["is_deleted"] is False


@pytest.mark.asyncio
async def test_edit_another_users_post_returns_403(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student cannot edit another user's post."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-403-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    other_post = await _make_post(db, lesson.id, admin_id, "Admin post")

    resp = await client.patch(
        f"/api/v1/discussions/{other_post.id}",
        json={"body": "Attempted edit"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "DISCUSSION_POST_FORBIDDEN"


@pytest.mark.asyncio
async def test_edit_nonexistent_post_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Editing a post that does not exist returns 404."""
    _, token = await _make_user(db, f"disc-404e-{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.patch(
        f"/api/v1/discussions/{uuid.uuid4()}",
        json={"body": "ghost"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404


# ── DELETE /discussions/{id} ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_soft_delete_own_post_leaves_tombstone(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Deleting a post replaces body with tombstone and sets is_deleted=True."""
    course, lesson, _ = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-del-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    post = await _make_post(db, lesson.id, student.id, "Will be deleted")

    resp = await client.delete(
        f"/api/v1/discussions/{post.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["body"] == TOMBSTONE
    assert data["is_deleted"] is True


@pytest.mark.asyncio
async def test_soft_delete_preserves_replies_and_thread_shape(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Soft-deleting a parent post leaves replies visible in the thread."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-shape-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)

    parent = await _make_post(db, lesson.id, student.id, "Parent post")
    reply = await _make_post(db, lesson.id, admin_id, "Reply to parent", parent_id=parent.id)

    # Soft-delete the parent
    del_resp = await client.delete(
        f"/api/v1/discussions/{parent.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 200

    # Parent still appears in the thread with tombstone body
    list_resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.status_code == 200
    posts = list_resp.json()["data"]
    parent_data = next((p for p in posts if p["id"] == str(parent.id)), None)
    assert parent_data is not None
    assert parent_data["body"] == TOMBSTONE
    assert parent_data["is_deleted"] is True

    # Reply is still visible under the parent
    reply_resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        params={"parent_id": str(parent.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reply_resp.status_code == 200
    reply_ids = [p["id"] for p in reply_resp.json()["data"]]
    assert str(reply.id) in reply_ids


@pytest.mark.asyncio
async def test_delete_another_users_post_returns_403(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student cannot soft-delete another user's post."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-403d-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    other_post = await _make_post(db, lesson.id, admin_id, "Admin post")

    resp = await client.delete(
        f"/api/v1/discussions/{other_post.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete_any_post(
    client: AsyncClient, db: AsyncSession
) -> None:
    """An admin can soft-delete a post they did not author."""
    course, lesson, admin_id = await _setup_lesson(db)
    _, admin_token = await _make_user(db, f"disc-adm2-{uuid.uuid4().hex[:6]}@example.com", "admin")
    student, _ = await _make_user(db, f"disc-stu-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    student_post = await _make_post(db, lesson.id, student.id, "Student post")

    resp = await client.delete(
        f"/api/v1/discussions/{student_post.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["is_deleted"] is True


@pytest.mark.asyncio
async def test_delete_already_deleted_post_returns_403(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Attempting to delete an already soft-deleted post returns 403."""
    course, lesson, _ = await _setup_lesson(db)
    student, token = await _make_user(db, f"disc-dd-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    post = await _make_post(db, lesson.id, student.id, "Will be deleted twice")

    await client.delete(
        f"/api/v1/discussions/{post.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.delete(
        f"/api/v1/discussions/{post.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "DISCUSSION_POST_FORBIDDEN"


# ── POST /discussions/{id}/upvote ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upvote_adds_vote_and_returns_count(
    client: AsyncClient, db: AsyncSession
) -> None:
    """First upvote on a post increments upvote_count to 1 and sets viewer_has_upvoted."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"vote-s1-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    post = await _make_post(db, lesson.id, admin_id, "Upvotable post")

    resp = await client.post(
        f"/api/v1/discussions/{post.id}/upvote",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["upvote_count"] == 1
    assert data["viewer_has_upvoted"] is True


@pytest.mark.asyncio
async def test_upvote_toggle_removes_vote(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A second upvote call on the same post removes the vote (toggle off)."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"vote-s2-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    post = await _make_post(db, lesson.id, admin_id, "Toggle post")

    # Vote on
    await client.post(
        f"/api/v1/discussions/{post.id}/upvote",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Vote off
    resp = await client.post(
        f"/api/v1/discussions/{post.id}/upvote",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["upvote_count"] == 0
    assert data["viewer_has_upvoted"] is False


@pytest.mark.asyncio
async def test_author_cannot_upvote_own_post(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The post author receives 403 when trying to upvote their own post."""
    course, lesson, _ = await _setup_lesson(db)
    student, token = await _make_user(db, f"vote-author-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    own_post = await _make_post(db, lesson.id, student.id, "My own post")

    resp = await client.post(
        f"/api/v1/discussions/{own_post.id}/upvote",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CANNOT_VOTE_ON_OWN_POST"


@pytest.mark.asyncio
async def test_vote_counts_returned_in_thread_listing(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Thread listing includes correct upvote_count and viewer_has_upvoted per post."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"vote-list-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)

    post_a = await _make_post(db, lesson.id, admin_id, "Post A")
    post_b = await _make_post(db, lesson.id, admin_id, "Post B")

    # Student upvotes only post_a
    await client.post(
        f"/api/v1/discussions/{post_a.id}/upvote",
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    posts = resp.json()["data"]

    a_data = next(p for p in posts if p["id"] == str(post_a.id))
    b_data = next(p for p in posts if p["id"] == str(post_b.id))

    assert a_data["upvote_count"] == 1
    assert a_data["viewer_has_upvoted"] is True
    assert b_data["upvote_count"] == 0
    assert b_data["viewer_has_upvoted"] is False


@pytest.mark.asyncio
async def test_upvote_nonexistent_post_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Upvoting a post that does not exist returns 404."""
    _, token = await _make_user(db, f"vote-404-{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.post(
        f"/api/v1/discussions/{uuid.uuid4()}/upvote",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DISCUSSION_POST_NOT_FOUND"


# ── POST /discussions/{id}/flag ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flag_post_creates_flag_in_queue(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Flagging a post creates a flag that appears in the admin moderation queue."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, student_token = await _make_user(db, f"flag-s1-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    _, admin_token = await _make_user(db, f"flag-adm-{uuid.uuid4().hex[:6]}@example.com", "admin")

    other_post = await _make_post(db, lesson.id, admin_id, "Flaggable post")

    flag_resp = await client.post(
        f"/api/v1/discussions/{other_post.id}/flag",
        json={"reason": "spam"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert flag_resp.status_code == 201
    flag_data = flag_resp.json()["data"]
    assert flag_data["reason"] == "spam"
    assert flag_data["status"] == "open"
    assert flag_data["post_id"] == str(other_post.id)

    # Appears in admin queue
    queue_resp = await client.get(
        "/api/v1/admin/moderation/flags",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert queue_resp.status_code == 200
    flag_ids = [f["id"] for f in queue_resp.json()["data"]]
    assert flag_data["id"] in flag_ids


@pytest.mark.asyncio
async def test_duplicate_flag_updates_existing_open_flag(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A second flag from the same user on the same post updates the existing open flag."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, token = await _make_user(db, f"flag-dup-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    other_post = await _make_post(db, lesson.id, admin_id, "Doubly flagged post")

    # First flag
    r1 = await client.post(
        f"/api/v1/discussions/{other_post.id}/flag",
        json={"reason": "spam"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 201
    flag_id_first = r1.json()["data"]["id"]

    # Second flag (should update, not create a new one)
    r2 = await client.post(
        f"/api/v1/discussions/{other_post.id}/flag",
        json={"reason": "harassment", "context": "Updated context"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 201
    flag_data_second = r2.json()["data"]

    # Same flag ID — updated in-place
    assert flag_data_second["id"] == flag_id_first
    assert flag_data_second["reason"] == "harassment"
    assert flag_data_second["context"] == "Updated context"


@pytest.mark.asyncio
async def test_author_cannot_flag_own_post(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The post author receives 403 when trying to flag their own post."""
    course, lesson, _ = await _setup_lesson(db)
    student, token = await _make_user(db, f"flag-author-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    own_post = await _make_post(db, lesson.id, student.id, "My own post")

    resp = await client.post(
        f"/api/v1/discussions/{own_post.id}/flag",
        json={"reason": "spam"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CANNOT_FLAG_OWN_POST"


# ── GET /admin/moderation/flags ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_moderation_queue_returns_open_flags_by_default(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Admin queue defaults to returning only open flags."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, student_token = await _make_user(db, f"queue-s-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    _, admin_token = await _make_user(db, f"queue-adm-{uuid.uuid4().hex[:6]}@example.com", "admin")
    other_post = await _make_post(db, lesson.id, admin_id, "Queued post")

    # Create a flag
    await client.post(
        f"/api/v1/discussions/{other_post.id}/flag",
        json={"reason": "off_topic"},
        headers={"Authorization": f"Bearer {student_token}"},
    )

    resp = await client.get(
        "/api/v1/admin/moderation/flags",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    flags = resp.json()["data"]
    assert len(flags) >= 1
    # All returned flags should be open
    for f in flags:
        assert f["status"] == "open"


@pytest.mark.asyncio
async def test_student_cannot_access_moderation_queue(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A student cannot access the admin moderation queue."""
    _, token = await _make_user(db, f"queue-403-{uuid.uuid4().hex[:6]}@example.com")

    resp = await client.get(
        "/api/v1/admin/moderation/flags",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── POST /admin/moderation/flags/{id}/resolve ──────────────────────────────────

@pytest.mark.asyncio
async def test_admin_resolves_flag_updates_queue_status(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Resolving a flag changes its status and removes it from the open queue."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, student_token = await _make_user(db, f"resolve-s-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    _, admin_token = await _make_user(db, f"resolve-adm-{uuid.uuid4().hex[:6]}@example.com", "admin")
    other_post = await _make_post(db, lesson.id, admin_id, "Post to resolve flag on")

    # Create the flag
    flag_resp = await client.post(
        f"/api/v1/discussions/{other_post.id}/flag",
        json={"reason": "spam"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    flag_id = flag_resp.json()["data"]["id"]

    # Resolve it
    resolve_resp = await client.post(
        f"/api/v1/admin/moderation/flags/{flag_id}/resolve",
        json={"outcome": "dismissed", "resolution_note": "Not actually spam"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resolve_resp.status_code == 200
    resolved = resolve_resp.json()["data"]
    assert resolved["status"] == "dismissed"
    assert resolved["resolution_note"] == "Not actually spam"
    assert resolved["resolved_by_id"] is not None
    assert resolved["resolved_at"] is not None


@pytest.mark.asyncio
async def test_resolve_with_content_removed_soft_deletes_post(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Resolving with content_removed outcome soft-deletes the flagged post."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, student_token = await _make_user(db, f"cr-s-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    _, admin_token = await _make_user(db, f"cr-adm-{uuid.uuid4().hex[:6]}@example.com", "admin")
    other_post = await _make_post(db, lesson.id, admin_id, "Content to be removed")

    flag_resp = await client.post(
        f"/api/v1/discussions/{other_post.id}/flag",
        json={"reason": "harassment"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    flag_id = flag_resp.json()["data"]["id"]

    await client.post(
        f"/api/v1/admin/moderation/flags/{flag_id}/resolve",
        json={"outcome": "content_removed"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # The post should now appear as deleted in the thread
    list_resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/discussions",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    posts = list_resp.json()["data"]
    post_data = next((p for p in posts if p["id"] == str(other_post.id)), None)
    assert post_data is not None
    assert post_data["is_deleted"] is True


@pytest.mark.asyncio
async def test_resolve_already_resolved_flag_returns_409(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Attempting to resolve an already-resolved flag returns 409."""
    course, lesson, admin_id = await _setup_lesson(db)
    student, student_token = await _make_user(db, f"rr-s-{uuid.uuid4().hex[:6]}@example.com")
    await _make_enrollment(db, student.id, course.id)
    _, admin_token = await _make_user(db, f"rr-adm-{uuid.uuid4().hex[:6]}@example.com", "admin")
    other_post = await _make_post(db, lesson.id, admin_id, "Post with double-resolve attempt")

    flag_resp = await client.post(
        f"/api/v1/discussions/{other_post.id}/flag",
        json={"reason": "spam"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    flag_id = flag_resp.json()["data"]["id"]

    # First resolution
    await client.post(
        f"/api/v1/admin/moderation/flags/{flag_id}/resolve",
        json={"outcome": "warned"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Second resolution — should conflict
    resp = await client.post(
        f"/api/v1/admin/moderation/flags/{flag_id}/resolve",
        json={"outcome": "dismissed"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DISCUSSION_FLAG_ALREADY_RESOLVED"
