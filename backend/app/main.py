"""FastAPI application factory — middleware, routers, and exception handlers."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.middleware import RequestIDMiddleware
from app.modules.admin.router import router as admin_router
from app.modules.batches.router import router as batches_router
from app.modules.placement.router import router as placement_router
from app.modules.programs.router import router as programs_router
from app.modules.ai.router import router as ai_router
from app.modules.assignments.router import router as assignments_router
from app.modules.auth.router import router as auth_router
from app.modules.certificates.router import router as certificates_router
from app.modules.coupons.router import router as coupons_router
from app.modules.courses.router import router as courses_router
from app.modules.discussions.router import router as discussions_router
from app.modules.enrollments.router import router as enrollments_router
from app.modules.media.router import router as media_router
from app.modules.notifications.router import router as notifications_router
from app.modules.payments.router import router as payments_router
from app.modules.subscriptions.router import router as subscriptions_router
from app.modules.quizzes.router import router as quizzes_router
from app.modules.rag.router import router as rag_router
from app.modules.users.router import router as users_router
from app.modules.video.router import router as video_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Verifies the database connection on startup and gracefully disposes the
    connection pool on shutdown.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control to the running application between startup and shutdown.
    """
    from app.db.session import engine

    async with engine.connect() as conn:
        await conn.close()
    yield
    await engine.dispose()


app = FastAPI(
    title="XOXO Education API",
    version="1.0.0",
    docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Middleware — outermost registered last
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.add_middleware(RequestIDMiddleware)

# Exception handlers
app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]

# Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(courses_router, prefix="/api/v1")
app.include_router(enrollments_router, prefix="/api/v1")
app.include_router(quizzes_router, prefix="/api/v1")
app.include_router(assignments_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(media_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(subscriptions_router, prefix="/api/v1")
app.include_router(coupons_router, prefix="/api/v1")
app.include_router(certificates_router, prefix="/api/v1")
app.include_router(video_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")
app.include_router(discussions_router, prefix="/api/v1")
app.include_router(batches_router, prefix="/api/v1")
app.include_router(placement_router, prefix="/api/v1")
app.include_router(programs_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    """Return a simple liveness probe response.

    Returns:
        A JSON object with ``{"status": "ok"}``.
    """
    return {"status": "ok"}
