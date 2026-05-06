import os
from collections.abc import AsyncGenerator

import pytest
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401 — register all models with Base.metadata
from app.db.base import Base
from app.db.session import get_db
from app.main import app as fastapi_app

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
TEST_DATABASE_URL_SYNC = os.environ["DATABASE_URL_SYNC"]
TEST_REDIS_URL = os.environ["REDIS_URL"]


def _ensure_test_database_exists() -> None:
    """Create the dedicated pytest database if it does not already exist."""
    test_url = make_url(TEST_DATABASE_URL_SYNC)
    database_name = test_url.database
    if not database_name:
        raise RuntimeError("DATABASE_URL_SYNC must include a database name for tests")

    admin_url = test_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def setup_database() -> None:
    """Reset the dedicated pytest database schema for a clean integration run."""
    _ensure_test_database_exists()
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
    """Reset the module-level Redis singleton and flush test Redis before each test.

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
    redis = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await redis.flushdb()
    finally:
        await redis.aclose()
    yield
    if redis_module._redis is not None:
        try:
            await redis_module._redis.aclose()
        except Exception:
            pass
        redis_module._redis = None
    redis = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await redis.flushdb()
    finally:
        await redis.aclose()


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
