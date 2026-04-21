import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401 — register all models with Base.metadata
from app.db.base import Base
from app.db.session import get_db
from app.main import app as fastapi_app

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
TEST_DATABASE_URL_SYNC = os.environ["DATABASE_URL_SYNC"]


@pytest.fixture(scope="session", autouse=True)
def setup_database() -> None:
    """Create tables using the ORM model definitions (includes generated columns)."""
    sync_engine = create_engine(TEST_DATABASE_URL_SYNC)
    Base.metadata.drop_all(sync_engine)
    with sync_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(sync_engine)
    yield
    Base.metadata.drop_all(sync_engine)
    sync_engine.dispose()


@pytest.fixture(autouse=True)
async def reset_redis_singleton() -> AsyncGenerator[None, None]:
    """Reset the module-level Redis singleton before each test.

    Each pytest-asyncio test runs in its own event loop.  The aioredis
    singleton in app.core.redis is bound to the event loop of the first test
    that touches it.  Subsequent tests run in a different loop and get a
    stale client, causing 'Event loop is closed' errors on teardown.  Clearing
    the singleton before every test forces a fresh client per loop.
    """
    import app.core.redis as redis_module

    if redis_module._redis is not None:
        try:
            await redis_module._redis.aclose()
        except Exception:
            pass
        redis_module._redis = None
    yield
    if redis_module._redis is not None:
        try:
            await redis_module._redis.aclose()
        except Exception:
            pass
        redis_module._redis = None


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Fresh async engine per test — connections stay within the test's event loop."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as c:
        yield c
    fastapi_app.dependency_overrides.clear()
