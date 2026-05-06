"""Pydantic schemas for placement test, attempts, and results."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


# ── Shared ─────────────────────────────────────────────────────────────────────

class PlacementOptionItem(BaseModel):
    """A single selectable option within a placement question.

    Attributes:
        id: Short identifier for this option (e.g. ``"a"``, ``"b"``).
        text: Display text shown to the student.
    """

    id: str
    text: str


# ── Placement test definition ──────────────────────────────────────────────────

class PlacementQuestionOut(BaseModel):
    """A single question returned as part of the active placement test.

    Correct answers are never included — they live only in the server-side
    constant and are used for scoring after submission.

    Attributes:
        id: Question identifier string (e.g. ``"q01"``).
        position: 1-based display order.
        stem: The question text shown to the student.
        options: Selectable answer options.
    """

    id: str
    position: int
    stem: str
    options: list[PlacementOptionItem]


class PlacementTestOut(BaseModel):
    """The active versioned placement test definition.

    Attributes:
        version: Identifier for the current question set (e.g. ``"v1"``).
            Stored in ``PlacementAttempt.meta`` so historical attempts can
            reference the exact question set used.
        total_questions: Total number of questions in this version.
        time_limit_minutes: Recommended client-side time budget.
        questions: Ordered list of questions without correct answers.
    """

    version: str
    total_questions: int
    time_limit_minutes: int
    questions: list[PlacementQuestionOut]


# ── Attempt submission ─────────────────────────────────────────────────────────

class PlacementAttemptIn(BaseModel):
    """Student's answers for a placement attempt.

    Attributes:
        answers: Maps question ID strings to a list containing the selected
            option ID.  Single-choice only — submitting more than one option
            for a question scores that question as incorrect.
        timing: Optional per-question time in milliseconds, keyed by question
            ID.  Stored in ``PlacementAttempt.meta`` for future analytics;
            not used for scoring.
    """

    answers: dict[str, list[str]]
    timing: dict[str, int] | None = None


class PlacementAttemptOut(BaseModel):
    """Immediate result returned after a successful placement submission.

    Attributes:
        attempt_id: UUID of the newly created ``PlacementAttempt``.
        raw_score: Number of questions answered correctly.
        max_score: Total number of questions (always 25 for v1).
        score_percent: ``raw_score / max_score * 100``, rounded to one decimal.
        level: XOXO diagnostic band label (e.g. ``"b1_to_b2"``).
        program_code: Short program identifier assigned (``"OC"``, ``"PT"``,
            or ``"FE"``).
        program_title: Human-readable program name.
        program_id: UUID of the assigned ``Program`` row.
    """

    attempt_id: uuid.UUID
    raw_score: int
    max_score: int
    score_percent: float
    level: str
    program_code: str
    program_title: str
    program_id: uuid.UUID


# ── Placement result ───────────────────────────────────────────────────────────

class PlacementResultOut(BaseModel):
    """Normalised placement outcome for the student-facing result endpoint.

    Attributes:
        id: ``PlacementResult`` UUID.
        user_id: The assessed student's UUID.
        attempt_id: The ``PlacementAttempt`` this result was derived from;
            ``None`` for admin-only overrides that bypassed assessment.
        program_id: UUID of the assigned program; ``None`` if the program was
            later archived.
        program_code: Short program identifier; ``None`` if program removed.
        program_title: Human-readable program name; ``None`` if program removed.
        level: XOXO diagnostic band label.
        is_override: ``True`` when set by an admin rather than auto-scored.
        assigned_at: Timestamp when this result row was created.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    attempt_id: uuid.UUID | None
    program_id: uuid.UUID | None
    program_code: str | None
    program_title: str | None
    level: str | None
    is_override: bool
    assigned_at: datetime

    model_config = {"from_attributes": True}


class AdminPlacementResultOut(PlacementResultOut):
    """Extended placement result for admin list and override endpoints.

    Adds student identity fields and raw scoring metadata pulled from
    ``PlacementAttempt.meta`` so admins can see the underlying numbers.

    Attributes:
        user_email: Email of the assessed student.
        user_display_name: Display name of the assessed student.
        raw_score: Correct answer count from the attempt; ``None`` for
            admin-created overrides with no associated attempt.
        max_score: Total question count from the attempt; ``None`` when no
            attempt exists.
        score_percent: Derived percentage; ``None`` when no attempt exists.
    """

    user_email: str
    user_display_name: str
    raw_score: int | None
    max_score: int | None
    score_percent: float | None


# ── Admin override ─────────────────────────────────────────────────────────────

class PlacementResultOverrideIn(BaseModel):
    """Admin payload for overriding a placement result.

    Attributes:
        program_id: UUID of the program to assign.
        level: XOXO diagnostic band label to store on the result.
    """

    program_id: uuid.UUID
    level: str
