import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.course import Course
from app.db.models.user import User, UserProfile


async def _seed_course(db: AsyncSession, title: str, status: str = "published") -> Course:
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("x"),
        role="admin",
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user_id, display_name="Admin"))
    course = Course(
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        title=title,
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status=status,
        created_by=user_id,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


@pytest.mark.asyncio
async def test_search_finds_matching_course(client: AsyncClient, db: AsyncSession) -> None:
    course = await _seed_course(db, "Advanced Python Programming")
    await _seed_course(db, "Introduction to JavaScript")

    resp = await client.get("/api/v1/search?q=python")
    assert resp.status_code == 200
    titles = [c["title"] for c in resp.json()["data"]]
    assert course.title in titles


@pytest.mark.asyncio
async def test_search_excludes_draft_courses(client: AsyncClient, db: AsyncSession) -> None:
    draft = await _seed_course(db, "Secret Draft Course", status="draft")

    resp = await client.get("/api/v1/search?q=secret")
    assert resp.status_code == 200
    titles = [c["title"] for c in resp.json()["data"]]
    assert draft.title not in titles


@pytest.mark.asyncio
async def test_search_empty_query_rejected(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/search?q=")
    assert resp.status_code == 422
