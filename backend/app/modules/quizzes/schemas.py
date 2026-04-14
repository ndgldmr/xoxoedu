"""Pydantic schemas for quizzes, questions, and submissions."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OptionItem(BaseModel):
    """A single selectable option within a quiz question.

    Attributes:
        id: Unique identifier for this option within the question.
        text: Display text shown to the student.
    """

    id: str
    text: str


# ── Admin input schemas ────────────────────────────────────────────────────────

class QuizQuestionIn(BaseModel):
    """Payload for creating a single quiz question.

    Attributes:
        position: 1-based display order within the quiz.
        kind: Question type — ``"single_choice"`` or ``"multi_choice"``.
        stem: The question text.
        options: Selectable answer options.
        correct_answers: IDs from ``options`` that constitute a correct response.
        points: Points awarded for a fully correct answer (default 1).
    """

    position: int = Field(ge=1)
    kind: str = Field(pattern="^(single_choice|multi_choice)$")
    stem: str
    options: list[OptionItem] = Field(min_length=2)
    correct_answers: list[str] = Field(min_length=1)
    points: int = Field(default=1, ge=1)


class QuizIn(BaseModel):
    """Payload for creating a quiz on a lesson.

    Attributes:
        lesson_id: The lesson this quiz is attached to.
        title: Short display name.
        description: Optional introductory text.
        max_attempts: Maximum submission attempts allowed (default 3).
        time_limit_minutes: Per-attempt time limit; ``None`` means unlimited.
        questions: Ordered list of questions to create with the quiz.
    """

    lesson_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    max_attempts: int = Field(default=3, ge=1)
    time_limit_minutes: int | None = Field(default=None, ge=1)
    questions: list[QuizQuestionIn] = Field(min_length=1)


# ── Output schemas ─────────────────────────────────────────────────────────────

class QuizQuestionOut(BaseModel):
    """Serialised quiz question returned to clients.

    ``correct_answers`` is always ``[]`` unless ``reveal=True`` is set
    internally — answers are only exposed after all attempts are exhausted.

    Attributes:
        id: Question UUID.
        position: Display order.
        kind: ``"single_choice"`` or ``"multi_choice"``.
        stem: Question text.
        options: Answer options (without indication of correctness).
        correct_answers: Correct option IDs; empty list when masked.
        points: Points for a fully correct response.
    """

    id: uuid.UUID
    position: int
    kind: str
    stem: str
    options: list[OptionItem]
    correct_answers: list[str]
    points: int

    model_config = {"from_attributes": True}


class QuizOut(BaseModel):
    """Full quiz representation returned to clients.

    Attributes:
        id: Quiz UUID.
        lesson_id: Parent lesson UUID.
        title: Display name.
        description: Introductory text.
        max_attempts: Maximum allowed attempts.
        time_limit_minutes: Optional per-attempt time limit.
        questions: Ordered questions with answers optionally masked.
    """

    id: uuid.UUID
    lesson_id: uuid.UUID
    title: str
    description: str | None
    max_attempts: int
    time_limit_minutes: int | None
    questions: list[QuizQuestionOut]

    model_config = {"from_attributes": True}


# ── AI feedback schemas ────────────────────────────────────────────────────────

class QuizFeedbackOut(BaseModel):
    """AI-generated feedback for a single question in a submission.

    Attributes:
        question_id: The question this feedback addresses.
        feedback_text: LLM-generated explanation; empty string when unavailable.
    """

    question_id: uuid.UUID
    feedback_text: str

    model_config = {"from_attributes": True}


# ── Submission schemas ─────────────────────────────────────────────────────────

class SubmitQuizIn(BaseModel):
    """Student's answers for a quiz attempt.

    Attributes:
        answers: Maps question UUID strings to lists of selected option IDs.
    """

    answers: dict[str, list[str]]


class QuizSubmissionOut(BaseModel):
    """Result of a quiz submission attempt.

    Attributes:
        id: Submission UUID.
        quiz_id: The quiz that was attempted.
        attempt_number: 1-based attempt counter for this student.
        score: Points earned.
        max_score: Maximum possible points.
        passed: ``True`` when ``score == max_score``.
        submitted_at: Server timestamp of the submission.
        questions: Questions with correct answers revealed when attempts exhausted.
        ai_feedback: Per-question AI feedback; empty list until the async task
            completes or when AI is disabled for the course.
    """

    id: uuid.UUID
    quiz_id: uuid.UUID
    attempt_number: int
    score: int
    max_score: int
    passed: bool
    submitted_at: datetime
    questions: list[QuizQuestionOut]
    ai_feedback: list[QuizFeedbackOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AttemptsRemainingOut(BaseModel):
    """Summary of attempt usage for a student on a quiz.

    Attributes:
        attempts_used: Number of submissions already made.
        max_attempts: Total allowed attempts.
        attempts_remaining: Attempts the student can still make.
    """

    attempts_used: int
    max_attempts: int
    attempts_remaining: int
