"""SQLAlchemy declarative base and reusable ORM mixins."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy declarative base; all ORM models inherit from this."""


class UUIDMixin:
    """Mixin that adds a UUID v4 primary key column named ``id``."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Mixin that adds ``created_at`` and ``updated_at`` timezone-aware timestamp columns.

    ``created_at`` is set by the database on INSERT via ``now()``.
    ``updated_at`` is set by the database on INSERT and updated in Python on
    every subsequent ORM-level mutation via ``onupdate``.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
