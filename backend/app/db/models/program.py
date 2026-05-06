"""ORM models for programs, program steps, and program enrollments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.db.models.course import Course
    from app.db.models.user import User


class Program(Base, UUIDMixin, TimestampMixin):
    """A business and academic container for a student's learning path.

    XOXO launches with three programs: ``PT`` (Pronunciation Training),
    ``FE`` (Fluent English), and ``OC`` (Online Communication).  A program
    owns ordered curriculum steps (``ProgramStep``) and cohort batches.  A
    student is placed into exactly one active program after completing the
    placement assessment.

    Attributes:
        code: Short unique identifier (e.g. ``"PT"``).  Used in seeds,
            placement logic, and admin tooling.
        title: Human-readable program name displayed in the UI.
        description: Optional long-form program description.
        marketing_summary: Optional short marketing blurb for public discovery.
        cover_image_url: Optional public-facing hero/card image URL.
        display_order: Stable ordering for public and admin listings.
        is_active: Controls whether the program appears in placement and
            enrollment flows.  Inactive programs are preserved for history.
        steps: Ordered ``ProgramStep`` records defining the curriculum.
    """

    __tablename__ = "programs"

    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketing_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    steps: Mapped[list[ProgramStep]] = relationship(
        "ProgramStep", back_populates="program", order_by="ProgramStep.position"
    )
    enrollments: Mapped[list[ProgramEnrollment]] = relationship(
        "ProgramEnrollment", back_populates="program"
    )


class ProgramStep(Base, UUIDMixin, TimestampMixin):
    """Ordered mapping between a program and a course.

    Defines the sequence of courses within a program.  A course may appear in
    at most one position per program (enforced by ``uq_program_steps_program_course``).
    Two steps in the same program cannot share the same position (enforced by
    ``uq_program_steps_program_position``).

    Attributes:
        program_id: FK to the owning program.
        course_id: FK to the content course at this step.
        position: 1-based ordering index within the program.
        is_required: Whether the student must complete this step before
            advancing.  Defaults to ``True``.
        program: The parent ``Program``.
        course: The ``Course`` at this curriculum position.
    """

    __tablename__ = "program_steps"
    __table_args__ = (
        UniqueConstraint("program_id", "course_id", name="uq_program_steps_program_course"),
        UniqueConstraint("program_id", "position", name="uq_program_steps_program_position"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    program: Mapped[Program] = relationship("Program", back_populates="steps")
    course: Mapped[Course] = relationship("Course", foreign_keys=[course_id])


class ProgramEnrollment(Base, UUIDMixin, TimestampMixin):
    """The student's assignment to a specific program.

    Only one ``active`` program enrollment is allowed per student at launch.
    Historical enrollments (``completed``, ``canceled``, ``suspended``) are
    preserved for audit and reporting purposes.

    The unique constraint ``uq_program_enrollments_user_program`` prevents a
    student from being enrolled in the same program twice; re-enrollment into
    the same program should reactivate an existing row rather than insert a
    new one.

    Status lifecycle: ``active`` ↔ ``suspended``; ``active`` → ``completed``;
    any status → ``canceled``.

    Attributes:
        user_id: FK to the enrolled student.
        program_id: FK to the assigned program.
        status: Current enrollment state.
        enrolled_at: DB-set timestamp when the record was first created.
        completed_at: Set when the student finishes the full program curriculum.
        user: The enrolled ``User``.
        program: The assigned ``Program``.
    """

    __tablename__ = "program_enrollments"
    __table_args__ = (
        UniqueConstraint("user_id", "program_id", name="uq_program_enrollments_user_program"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    program: Mapped[Program] = relationship("Program", back_populates="enrollments")
