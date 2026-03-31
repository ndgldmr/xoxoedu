import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Course
from app.db.models.user import User, UserProfile


async def _make_user(db: AsyncSession, email: str, role: str = "student") -> tuple[User, str]:
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


async def _make_course(
    db: AsyncSession,
    created_by: uuid.UUID,
    title: str = "Test Course",
    status: str = "draft",
    slug: str | None = None,
) -> Course:
    course = Course(
        slug=slug or f"test-course-{uuid.uuid4().hex[:6]}",
        title=title,
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status=status,
        created_by=created_by,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


# ── Course CRUD ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_course_as_admin(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-cc@example.com", role="admin")
    resp = await client.post(
        "/api/v1/admin/courses",
        json={"title": "Intro to Python", "level": "beginner"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["title"] == "Intro to Python"
    assert data["slug"] == "intro-to-python"
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_create_course_forbidden_for_student(client: AsyncClient, db: AsyncSession) -> None:
    _, token = await _make_user(db, "student-cc@example.com")
    resp = await client.post(
        "/api/v1/admin/courses",
        json={"title": "Hacking Course", "level": "beginner"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_courses_only_returns_published(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-lc@example.com", role="admin")
    await _make_course(db, admin.id, title="Draft Course", status="draft")
    published = await _make_course(db, admin.id, title="Published Course", status="published")

    resp = await client.get("/api/v1/courses")
    assert resp.status_code == 200
    slugs = [c["slug"] for c in resp.json()["data"]]
    assert published.slug in slugs
    published_items = [c for c in resp.json()["data"] if c["slug"] == published.slug]
    assert all(c["status"] == "published" for c in published_items)


@pytest.mark.asyncio
async def test_get_course_by_slug(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, "admin-gs@example.com", role="admin")
    course = await _make_course(
        db, admin.id, title="Slug Course", status="published", slug="slug-course-unique"
    )

    resp = await client.get(f"/api/v1/courses/{course.slug}")
    assert resp.status_code == 200
    assert resp.json()["data"]["slug"] == course.slug


@pytest.mark.asyncio
async def test_get_draft_course_by_slug_returns_404(client: AsyncClient, db: AsyncSession) -> None:
    admin, _ = await _make_user(db, "admin-gd@example.com", role="admin")
    course = await _make_course(
        db, admin.id, title="Draft Only", status="draft", slug="draft-only-unique"
    )

    resp = await client.get(f"/api/v1/courses/{course.slug}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_course(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-uc@example.com", role="admin")
    course = await _make_course(db, admin.id)

    resp = await client.patch(
        f"/api/v1/admin/courses/{course.id}",
        json={"title": "Updated Title"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_publish_course(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-pub@example.com", role="admin")
    course = await _make_course(db, admin.id, slug="pub-course-unique")

    resp = await client.patch(
        f"/api/v1/admin/courses/{course.id}",
        json={"status": "published"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "published"

    list_resp = await client.get("/api/v1/courses")
    slugs = [c["slug"] for c in list_resp.json()["data"]]
    assert course.slug in slugs


@pytest.mark.asyncio
async def test_archive_course_removes_from_list(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-arc@example.com", role="admin")
    course = await _make_course(db, admin.id, slug="arc-course-unique", status="published")

    resp = await client.delete(
        f"/api/v1/admin/courses/{course.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204

    list_resp = await client.get("/api/v1/courses")
    slugs = [c["slug"] for c in list_resp.json()["data"]]
    assert course.slug not in slugs


@pytest.mark.asyncio
async def test_slug_immutable_after_publication(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-si@example.com", role="admin")
    course = await _make_course(db, admin.id, slug="immutable-slug-unique", status="published")

    resp = await client.patch(
        f"/api/v1/admin/courses/{course.id}",
        json={"slug": "new-slug"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "SLUG_IMMUTABLE"


# ── Chapters ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_chapter_auto_position(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-ch@example.com", role="admin")
    course = await _make_course(db, admin.id)

    resp1 = await client.post(
        f"/api/v1/admin/courses/{course.id}/chapters",
        json={"title": "Chapter One"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 201
    assert resp1.json()["data"]["position"] == 1

    resp2 = await client.post(
        f"/api/v1/admin/courses/{course.id}/chapters",
        json={"title": "Chapter Two"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 201
    assert resp2.json()["data"]["position"] == 2


@pytest.mark.asyncio
async def test_reorder_chapters(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-rch@example.com", role="admin")
    course = await _make_course(db, admin.id)

    ch1 = await client.post(
        f"/api/v1/admin/courses/{course.id}/chapters",
        json={"title": "A"},
        headers={"Authorization": f"Bearer {token}"},
    )
    ch2 = await client.post(
        f"/api/v1/admin/courses/{course.id}/chapters",
        json={"title": "B"},
        headers={"Authorization": f"Bearer {token}"},
    )
    id1 = ch1.json()["data"]["id"]
    id2 = ch2.json()["data"]["id"]

    resp = await client.patch(
        f"/api/v1/admin/courses/{course.id}/chapters/reorder",
        json={"ids": [id2, id1]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    positions = {c["id"]: c["position"] for c in resp.json()["data"]}
    assert positions[id2] == 1
    assert positions[id1] == 2


@pytest.mark.asyncio
async def test_delete_chapter(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-dch@example.com", role="admin")
    course = await _make_course(db, admin.id)

    ch = await client.post(
        f"/api/v1/admin/courses/{course.id}/chapters",
        json={"title": "To Delete"},
        headers={"Authorization": f"Bearer {token}"},
    )
    chapter_id = ch.json()["data"]["id"]

    resp = await client.delete(
        f"/api/v1/admin/chapters/{chapter_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204


# ── Lessons ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_lesson_auto_position(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-ls@example.com", role="admin")
    course = await _make_course(db, admin.id)
    ch = await client.post(
        f"/api/v1/admin/courses/{course.id}/chapters",
        json={"title": "Ch"},
        headers={"Authorization": f"Bearer {token}"},
    )
    chapter_id = ch.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/admin/chapters/{chapter_id}/lessons",
        json={"title": "Lesson 1", "type": "text", "content": {"body": "hello"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["position"] == 1


@pytest.mark.asyncio
async def test_reorder_lessons(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-rls@example.com", role="admin")
    course = await _make_course(db, admin.id)
    ch = await client.post(
        f"/api/v1/admin/courses/{course.id}/chapters",
        json={"title": "Ch"},
        headers={"Authorization": f"Bearer {token}"},
    )
    chapter_id = ch.json()["data"]["id"]

    l1 = await client.post(
        f"/api/v1/admin/chapters/{chapter_id}/lessons",
        json={"title": "A", "type": "text", "content": {"body": "a"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    l2 = await client.post(
        f"/api/v1/admin/chapters/{chapter_id}/lessons",
        json={"title": "B", "type": "text", "content": {"body": "b"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    id1 = l1.json()["data"]["id"]
    id2 = l2.json()["data"]["id"]

    resp = await client.patch(
        f"/api/v1/admin/chapters/{chapter_id}/lessons/reorder",
        json={"ids": [id2, id1]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    positions = {ls["id"]: ls["position"] for ls in resp.json()["data"]}
    assert positions[id2] == 1
    assert positions[id1] == 2


# ── Resources ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_attach_resource(client: AsyncClient, db: AsyncSession) -> None:
    admin, token = await _make_user(db, "admin-res@example.com", role="admin")
    course = await _make_course(db, admin.id)
    ch = await client.post(
        f"/api/v1/admin/courses/{course.id}/chapters",
        json={"title": "Ch"},
        headers={"Authorization": f"Bearer {token}"},
    )
    ls = await client.post(
        f"/api/v1/admin/chapters/{ch.json()['data']['id']}/lessons",
        json={"title": "L", "type": "text", "content": {"body": "x"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    lesson_id = ls.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/admin/lessons/{lesson_id}/resources",
        json={"name": "Cheatsheet", "file_url": "https://example.com/file.pdf"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["name"] == "Cheatsheet"
