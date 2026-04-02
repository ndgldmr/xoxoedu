"""ORM models for quizzes, quiz questions, and quiz submissions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Lesson
    from app.db.models.user import User


class Quiz(Base, UUIDMixin, TimestampMixin):
    """A quiz attached to a lesson, supporting multiple timed attempts.

    Each quiz has an ordered list of ``QuizQuestion`` rows.  Students submit
    ``QuizSubmission`` rows up to ``max_attempts`` times.

    Attributes:
        lesson_id: FK to the lesson this quiz belongs to; cascades on delete.
        title: Short display name for the quiz.
        description: Optional introductory text shown before the first question.
        max_attempts: Maximum number of submission attempts allowed (default 3).
        time_limit_minutes: Optional per-attempt time limit; ``None`` means unlimited.
        lesson: The parent ``Lesson``.
        questions: Ordered list of ``QuizQuestion`` rows.
    """

    __tablename__ = "quizzes"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    lesson: Mapped[Lesson] = relationship("Lesson", foreign_keys=[lesson_id])
    questions: Mapped[list[QuizQuestion]] = relationship(
        "QuizQuestion",
        back_populates="quiz",
        order_by="QuizQuestion.position",
        cascade="all, delete-orphan",
    )


class QuizQuestion(Base, UUIDMixin, TimestampMixin):
    """A single question within a quiz.

    Supports two question kinds: ``single_choice`` (exactly one correct answer)
    and ``multi_choice`` (all correct options must be selected for full points).
    Correct answer IDs are stored in ``correct_answers`` and are never sent to
    students until they have exhausted all attempts.

    Attributes:
        quiz_id: FK to the parent quiz; cascades on delete.
        position: 1-based display order within the quiz.
        kind: Question type — ``"single_choice"`` or ``"multi_choice"``.
        stem: The question text (may contain Markdown).
        options: List of ``{"id": str, "text": str}`` dicts presented to students.
        correct_answers: List of option IDs that constitute a correct answer.
        points: Points awarded for a fully correct response (default 1).
        quiz: The parent ``Quiz``.
    """

    __tablename__ = "quiz_questions"

    quiz_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    correct_answers: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    quiz: Mapped[Quiz] = relationship("Quiz", back_populates="questions")


class QuizSubmission(Base, UUIDMixin):
    """Records one attempt at a quiz by a student.

    The ``UniqueConstraint`` on ``(user_id, quiz_id, attempt_number)`` acts as
    a TOCTOU guard — concurrent duplicate submissions are caught at the DB level
    and converted to a 409 by the service layer.

    Attributes:
        user_id: FK to the submitting student; cascades on user delete.
        quiz_id: FK to the quiz being attempted; cascades on quiz delete.
        attempt_number: 1-based counter for this student's attempts on the quiz.
        answers: ``{question_id: [option_ids]}`` mapping supplied by the student.
        score: Points earned on this attempt.
        max_score: Maximum points possible across all questions.
        passed: ``True`` if ``score >= max_score`` (100% required by default).
        submitted_at: Server timestamp recorded when the row is inserted.
        user: The submitting ``User``.
        quiz: The ``Quiz`` that was attempted.
    """

    __tablename__ = "quiz_submissions"
    __table_args__ = (
        UniqueConstraint("user_id", "quiz_id", "attempt_number", name="uq_quiz_attempt"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    quiz: Mapped[Quiz] = relationship("Quiz", foreign_keys=[quiz_id])
