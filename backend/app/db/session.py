"""Async SQLAlchemy engine, session factory, and FastAPI session dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional async database session for use as a FastAPI dependency.

    Automatically commits on success and rolls back on any exception, then
    closes the session when the request completes.

    Yields:
        An ``AsyncSession`` bound to a single database transaction.

    Raises:
        Exception: Re-raises any exception that occurs inside the ``with`` block
            after rolling back the transaction.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
