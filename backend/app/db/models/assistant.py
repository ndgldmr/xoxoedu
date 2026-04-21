"""ORM models for the AI course assistant conversations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Course, Lesson
    from app.db.models.user import User


class Conversation(Base, UUIDMixin, TimestampMixin):
    """A persistent chat thread between a student and the course AI assistant.

    One conversation exists per ``(user_id, course_id)`` pair — the POST
    endpoint creates it on first use and continues it on every subsequent call.

    Attributes:
        user_id: FK to the student who owns this conversation.
        course_id: FK to the course this conversation is scoped to.
        messages: Ordered list of turns, newest last.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_conversation_user_course"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    messages: Mapped[list[ConversationMessage]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        order_by="ConversationMessage.created_at",
        cascade="all, delete-orphan",
    )
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    course: Mapped[Course] = relationship("Course", foreign_keys=[course_id])


class ConversationMessage(Base, UUIDMixin):
    """A single turn in a conversation.

    Attributes:
        conversation_id: FK to the parent conversation; cascades on delete.
        role: ``"user"`` for student questions, ``"assistant"`` for LLM replies.
        content: Full text of the turn.
        created_at: Server timestamp; determines ordering within a conversation.
    """

    __tablename__ = "conversation_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages"
    )
