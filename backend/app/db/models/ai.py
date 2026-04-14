"""ORM models for AI usage logging and per-course AI configuration."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Course
    from app.db.models.user import User


class AIUsageLog(Base, UUIDMixin):
    """Append-only record of a single LLM call.

    Written asynchronously by a Celery task after the call completes to avoid
    hot-row contention on the request path.  Both ``user_id`` and ``course_id``
    use SET NULL on delete so logs are preserved for billing audits even after
    a user or course is removed.

    Attributes:
        user_id: FK to the user who triggered the call; nullable.
        course_id: FK to the associated course; nullable.
        feature: Short tag identifying which product feature made the call
            (e.g. ``"quiz_feedback"``, ``"assignment_feedback"``, ``"rag"``).
        tokens_in: Prompt token count as reported by the provider.
        tokens_out: Completion token count as reported by the provider.
        model: Full model identifier used for the call (e.g. ``"gemini/gemini-2.0-flash"``).
        created_at: Server timestamp set on INSERT.
    """

    __tablename__ = "ai_usage_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])
    course: Mapped[Course | None] = relationship("Course", foreign_keys=[course_id])


class AIUsageBudget(Base, UUIDMixin, TimestampMixin):
    """Admin-configurable AI settings and token budget for a single course.

    One row per course; missing rows are treated as defaults by the service
    layer so this table stays sparse until an admin explicitly customises a
    course.

    Attributes:
        course_id: FK to the course; unique — one config per course.
        ai_enabled: Master switch; ``False`` prevents any LLM calls for the course.
        tone: Feedback tone injected into the system prompt
            (``"encouraging"``, ``"neutral"``, or ``"strict"``).
        system_prompt_override: Optional full replacement for the default system
            prompt; ``None`` means use the Jinja2 base template.
        monthly_token_limit: Hard cap on tokens consumed per month for this
            course, enforced via the Redis quota system.
        alert_threshold: Fraction of ``monthly_token_limit`` at which an admin
            alert is triggered (default ``0.8`` = 80 %).
    """

    __tablename__ = "ai_usage_budgets"

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tone: Mapped[str] = mapped_column(String(20), nullable=False, default="encouraging")
    system_prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    monthly_token_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100_000
    )
    alert_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)

    course: Mapped[Course] = relationship("Course", foreign_keys=[course_id])
