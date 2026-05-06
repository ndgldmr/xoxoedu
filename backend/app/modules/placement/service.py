"""Business logic for placement test retrieval, scoring, and result management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    NoPlacementResult,
    PlacementResultNotFound,
    ProgramNotFound,
)
from app.db.models.placement import PlacementAttempt, PlacementResult
from app.db.models.program import Program, ProgramEnrollment
from app.db.models.user import User
from app.modules.placement.schemas import (
    AdminPlacementResultOut,
    PlacementAttemptIn,
    PlacementAttemptOut,
    PlacementOptionItem,
    PlacementQuestionOut,
    PlacementResultOut,
    PlacementResultOverrideIn,
    PlacementTestOut,
)

# ── Placement test definition ──────────────────────────────────────────────────
# XOXO-owned English assessment questions spanning A2–C1 difficulty.
# The ``correct`` key is never serialised — it is used only by _score_placement.

PLACEMENT_TEST_VERSION = "v1"
PLACEMENT_TIME_LIMIT_MINUTES = 30

_PLACEMENT_QUESTIONS: list[dict] = [
    # ── A2-level vocabulary and grammar (q01–q08) ─────────────────────────────
    {
        "id": "q01", "position": 1,
        "stem": "She _____ to work every day by bus.",
        "options": [{"id": "a", "text": "go"}, {"id": "b", "text": "goes"},
                    {"id": "c", "text": "going"}, {"id": "d", "text": "gone"}],
        "correct": "b",
    },
    {
        "id": "q02", "position": 2,
        "stem": "There _____ any milk in the fridge.",
        "options": [{"id": "a", "text": "are"}, {"id": "b", "text": "isn't"},
                    {"id": "c", "text": "aren't"}, {"id": "d", "text": "is"}],
        "correct": "b",
    },
    {
        "id": "q03", "position": 3,
        "stem": "We _____ dinner when the phone rang.",
        "options": [{"id": "a", "text": "had"}, {"id": "b", "text": "have had"},
                    {"id": "c", "text": "were having"}, {"id": "d", "text": "have"}],
        "correct": "c",
    },
    {
        "id": "q04", "position": 4,
        "stem": "Which word means the opposite of 'expensive'?",
        "options": [{"id": "a", "text": "rare"}, {"id": "b", "text": "cheap"},
                    {"id": "c", "text": "heavy"}, {"id": "d", "text": "fast"}],
        "correct": "b",
    },
    {
        "id": "q05", "position": 5,
        "stem": "I have lived in this city _____ ten years.",
        "options": [{"id": "a", "text": "since"}, {"id": "b", "text": "ago"},
                    {"id": "c", "text": "for"}, {"id": "d", "text": "during"}],
        "correct": "c",
    },
    {
        "id": "q06", "position": 6,
        "stem": "He asked me _____ I wanted to join the team.",
        "options": [{"id": "a", "text": "that"}, {"id": "b", "text": "what"},
                    {"id": "c", "text": "if"}, {"id": "d", "text": "which"}],
        "correct": "c",
    },
    {
        "id": "q07", "position": 7,
        "stem": "Which sentence is correct?",
        "options": [
            {"id": "a", "text": "I am agree with you."},
            {"id": "b", "text": "I agree with you."},
            {"id": "c", "text": "I agreeing with you."},
            {"id": "d", "text": "I do agree to you."},
        ],
        "correct": "b",
    },
    {
        "id": "q08", "position": 8,
        "stem": "The film _____ two hours ago.",
        "options": [{"id": "a", "text": "starts"}, {"id": "b", "text": "has started"},
                    {"id": "c", "text": "started"}, {"id": "d", "text": "is starting"}],
        "correct": "c",
    },
    # ── B1-level grammar and usage (q09–q16) ──────────────────────────────────
    {
        "id": "q09", "position": 9,
        "stem": "By the time we arrived, the meeting _____.",
        "options": [{"id": "a", "text": "already finished"}, {"id": "b", "text": "has finished"},
                    {"id": "c", "text": "had already finished"}, {"id": "d", "text": "was finishing"}],
        "correct": "c",
    },
    {
        "id": "q10", "position": 10,
        "stem": "If I _____ more time, I would learn a new language.",
        "options": [{"id": "a", "text": "have"}, {"id": "b", "text": "had"},
                    {"id": "c", "text": "would have"}, {"id": "d", "text": "will have"}],
        "correct": "b",
    },
    {
        "id": "q11", "position": 11,
        "stem": "The report _____ by the end of the week.",
        "options": [{"id": "a", "text": "will finish"}, {"id": "b", "text": "is finishing"},
                    {"id": "c", "text": "will be finished"}, {"id": "d", "text": "finishes"}],
        "correct": "c",
    },
    {
        "id": "q12", "position": 12,
        "stem": "She suggested _____ the meeting until Friday.",
        "options": [{"id": "a", "text": "to postpone"}, {"id": "b", "text": "postpone"},
                    {"id": "c", "text": "postponing"}, {"id": "d", "text": "postponed"}],
        "correct": "c",
    },
    {
        "id": "q13", "position": 13,
        "stem": "Despite _____ hard, he failed the exam.",
        "options": [{"id": "a", "text": "studied"}, {"id": "b", "text": "studying"},
                    {"id": "c", "text": "to study"}, {"id": "d", "text": "study"}],
        "correct": "b",
    },
    {
        "id": "q14", "position": 14,
        "stem": "Which word best completes: 'The instructions were so _____ that nobody understood them'?",
        "options": [{"id": "a", "text": "vague"}, {"id": "b", "text": "precise"},
                    {"id": "c", "text": "brief"}, {"id": "d", "text": "simple"}],
        "correct": "a",
    },
    {
        "id": "q15", "position": 15,
        "stem": "The manager made it clear that punctuality _____ be taken seriously.",
        "options": [{"id": "a", "text": "can"}, {"id": "b", "text": "might"},
                    {"id": "c", "text": "was to"}, {"id": "d", "text": "used to"}],
        "correct": "c",
    },
    {
        "id": "q16", "position": 16,
        "stem": "Not only _____ late, but he also forgot the documents.",
        "options": [{"id": "a", "text": "he arrived"}, {"id": "b", "text": "did he arrive"},
                    {"id": "c", "text": "he did arrive"}, {"id": "d", "text": "arrived he"}],
        "correct": "b",
    },
    # ── B2-level vocabulary and complex grammar (q17–q22) ─────────────────────
    {
        "id": "q17", "position": 17,
        "stem": "The proposal _____ had it not been for the director's support.",
        "options": [{"id": "a", "text": "would rejected"}, {"id": "b", "text": "would have rejected"},
                    {"id": "c", "text": "would have been rejected"}, {"id": "d", "text": "had rejected"}],
        "correct": "c",
    },
    {
        "id": "q18", "position": 18,
        "stem": "Which sentence uses 'which' correctly?",
        "options": [
            {"id": "a", "text": "The book which I borrowed it was fascinating."},
            {"id": "b", "text": "The book, which I borrowed, was fascinating."},
            {"id": "c", "text": "The book which was fascinating I borrowed."},
            {"id": "d", "text": "The book that which I borrowed was fascinating."},
        ],
        "correct": "b",
    },
    {
        "id": "q19", "position": 19,
        "stem": "Her argument was _____, leaving no room for counterpoints.",
        "options": [{"id": "a", "text": "conclusive"}, {"id": "b", "text": "ambiguous"},
                    {"id": "c", "text": "redundant"}, {"id": "d", "text": "tentative"}],
        "correct": "a",
    },
    {
        "id": "q20", "position": 20,
        "stem": "The word 'mitigate' most closely means:",
        "options": [{"id": "a", "text": "to worsen"}, {"id": "b", "text": "to ignore"},
                    {"id": "c", "text": "to lessen"}, {"id": "d", "text": "to delay"}],
        "correct": "c",
    },
    {
        "id": "q21", "position": 21,
        "stem": "Scarcely _____ sat down when the alarm sounded.",
        "options": [{"id": "a", "text": "she had"}, {"id": "b", "text": "had she"},
                    {"id": "c", "text": "she has"}, {"id": "d", "text": "has she"}],
        "correct": "b",
    },
    {
        "id": "q22", "position": 22,
        "stem": "The new policy is intended to _____ the gap between high and low earners.",
        "options": [{"id": "a", "text": "broaden"}, {"id": "b", "text": "narrow"},
                    {"id": "c", "text": "extend"}, {"id": "d", "text": "deepen"}],
        "correct": "b",
    },
    # ── C1-level precision and nuance (q23–q25) ───────────────────────────────
    {
        "id": "q23", "position": 23,
        "stem": "The committee _____ to reach a consensus after three hours of debate.",
        "options": [{"id": "a", "text": "managed"}, {"id": "b", "text": "succeeded"},
                    {"id": "c", "text": "achieved"}, {"id": "d", "text": "accomplished"}],
        "correct": "a",
    },
    {
        "id": "q24", "position": 24,
        "stem": "Which of the following is the most formal register?",
        "options": [
            {"id": "a", "text": "We need to wrap up this deal ASAP."},
            {"id": "b", "text": "Let's close this deal quickly."},
            {"id": "c", "text": "It is imperative that we conclude this agreement promptly."},
            {"id": "d", "text": "We've got to finish this deal soon."},
        ],
        "correct": "c",
    },
    {
        "id": "q25", "position": 25,
        "stem": "The phrase 'to turn a blind eye' means:",
        "options": [{"id": "a", "text": "to look carefully at something"},
                    {"id": "b", "text": "to deliberately ignore something"},
                    {"id": "c", "text": "to misunderstand something"},
                    {"id": "d", "text": "to become temporarily unable to see"}],
        "correct": "b",
    },
]

# Band map: (min_score_inclusive, max_score_inclusive, level_label, program_code)
# Both 0–5 (below A2) and 6–12 (A2/borderline B1) map to OC — merged under
# "a2_or_below" for simplicity.  The label is stored for analytics and can be
# split back into two bands later without touching the API contract.
_BAND_MAP: list[tuple[int, int, str, str]] = [
    (0,  12, "a2_or_below", "OC"),
    (13, 19, "b1_to_b2",   "PT"),
    (20, 25, "b2_plus",    "FE"),
]


# ── Pure scoring helpers ───────────────────────────────────────────────────────

def _compute_band(raw_score: int) -> tuple[str, str]:
    """Return ``(level_label, program_code)`` for a placement raw score.

    Args:
        raw_score: Integer score in the range 0–25.

    Returns:
        A ``(level_label, program_code)`` tuple from ``_BAND_MAP``.

    Raises:
        ValueError: When ``raw_score`` is outside the valid 0–25 range.
    """
    for lo, hi, label, code in _BAND_MAP:
        if lo <= raw_score <= hi:
            return label, code
    raise ValueError(f"raw_score {raw_score} is outside the valid range 0–25")


def _score_placement(answers: dict[str, list[str]]) -> tuple[int, int]:
    """Score a placement submission against the current question set.

    Single-choice scoring: exactly one submitted option must match the stored
    correct answer.  Submitting zero or more than one option scores the
    question as incorrect.  Questions absent from ``answers`` score as 0.

    Args:
        answers: ``{question_id: [option_ids]}`` mapping from the student.

    Returns:
        A ``(raw_score, max_score)`` tuple; ``max_score`` equals the total
        number of questions in the active test (25 for v1).
    """
    score = 0
    for q in _PLACEMENT_QUESTIONS:
        given = answers.get(q["id"], [])
        if len(given) == 1 and given[0] == q["correct"]:
            score += 1
    return score, len(_PLACEMENT_QUESTIONS)


# ── Async service functions ────────────────────────────────────────────────────

async def get_active_placement_test(db: AsyncSession) -> PlacementTestOut:
    """Return the active versioned placement test definition.

    No database query is performed — the definition is a server-side constant.
    Correct answers are never included in the returned object.

    Args:
        db: Active async database session (unused; kept for interface consistency).

    Returns:
        A ``PlacementTestOut`` with all questions and no correct answers.
    """
    return PlacementTestOut(
        version=PLACEMENT_TEST_VERSION,
        total_questions=len(_PLACEMENT_QUESTIONS),
        time_limit_minutes=PLACEMENT_TIME_LIMIT_MINUTES,
        questions=[
            PlacementQuestionOut(
                id=q["id"],
                position=q["position"],
                stem=q["stem"],
                options=[PlacementOptionItem(**opt) for opt in q["options"]],
            )
            for q in _PLACEMENT_QUESTIONS
        ],
    )


async def _swap_program_enrollment(
    db: AsyncSession, user_id: uuid.UUID, target_program_id: uuid.UUID
) -> None:
    """Deactivate competing active enrollments and activate the target program.

    Steps (within the caller's open transaction — does NOT commit):

    1. Suspend any ``active`` enrollments for programs *other than* the target.
    2. Load the enrollment for the target program, if it exists.
       - If it exists and is not ``active``: set ``status='active'`` and clear
         ``completed_at``.
       - If it does not exist: insert a new ``active`` enrollment.

    The ``uq_program_enrollments_user_program`` unique constraint means a
    second INSERT for the same (user, program) pair would fail; this function
    guards against that by always checking first.

    Args:
        db: Active async database session (transaction not committed here).
        user_id: UUID of the student.
        target_program_id: UUID of the program to enroll the student into.
    """
    # Suspend any other active enrollments
    await db.execute(
        update(ProgramEnrollment)
        .where(
            ProgramEnrollment.user_id == user_id,
            ProgramEnrollment.status == "active",
            ProgramEnrollment.program_id != target_program_id,
        )
        .values(status="suspended")
    )

    # Upsert the target enrollment
    result = await db.execute(
        select(ProgramEnrollment).where(
            ProgramEnrollment.user_id == user_id,
            ProgramEnrollment.program_id == target_program_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if existing.status != "active":
            existing.status = "active"
            existing.completed_at = None
    else:
        db.add(
            ProgramEnrollment(
                user_id=user_id,
                program_id=target_program_id,
                status="active",
            )
        )


async def submit_placement_attempt(
    db: AsyncSession, user_id: uuid.UUID, data: PlacementAttemptIn
) -> PlacementAttemptOut:
    """Score a placement submission and create the attempt, result, and enrollment.

    All writes are performed in a single transaction:

    1. Score the answers using the current question set.
    2. Map the score to a diagnostic band and target program code.
    3. Persist a ``PlacementAttempt`` with answers, score, and metadata.
    4. Look up the target ``Program`` by code.
    5. Persist a ``PlacementResult`` linking the attempt to the program.
    6. Deactivate competing enrollments and activate the target program.
    7. Commit.

    Args:
        db: Active async database session.
        user_id: UUID of the submitting student.
        data: ``PlacementAttemptIn`` containing answers and optional timing.

    Returns:
        A ``PlacementAttemptOut`` with score, band, and assigned program.

    Raises:
        ProgramNotFound: When the target program (OC/PT/FE) does not exist in
            the database.  This indicates a seeding issue, not a client error.
    """
    raw_score, max_score = _score_placement(data.answers)
    level, program_code = _compute_band(raw_score)
    score_percent = round(raw_score / max_score * 100, 1)
    now = datetime.now(UTC)

    attempt = PlacementAttempt(
        user_id=user_id,
        answers=data.answers,
        score=raw_score,
        started_at=now,
        completed_at=now,
        meta={
            "version": PLACEMENT_TEST_VERSION,
            "max_score": max_score,
            "score_percent": score_percent,
            **({"timing": data.timing} if data.timing is not None else {}),
        },
    )
    db.add(attempt)
    await db.flush()  # populate attempt.id before using it in PlacementResult

    prog_result = await db.execute(
        select(Program).where(Program.code == program_code, Program.is_active.is_(True))
    )
    program = prog_result.scalar_one_or_none()
    if program is None:
        raise ProgramNotFound(f"Program with code '{program_code}' not found or inactive")

    placement_result = PlacementResult(
        user_id=user_id,
        attempt_id=attempt.id,
        program_id=program.id,
        level=level,
        is_override=False,
    )
    db.add(placement_result)

    await _swap_program_enrollment(db, user_id, program.id)

    await db.commit()

    return PlacementAttemptOut(
        attempt_id=attempt.id,
        raw_score=raw_score,
        max_score=max_score,
        score_percent=score_percent,
        level=level,
        program_code=program.code,
        program_title=program.title,
        program_id=program.id,
    )


async def get_my_placement_result(
    db: AsyncSession, user_id: uuid.UUID
) -> PlacementResultOut:
    """Return the most recent placement result for a student.

    Args:
        db: Active async database session.
        user_id: UUID of the requesting student.

    Returns:
        A ``PlacementResultOut`` with the latest result and program details.

    Raises:
        NoPlacementResult: When the student has not yet completed the assessment.
    """
    result = await db.execute(
        select(PlacementResult)
        .where(PlacementResult.user_id == user_id)
        .options(selectinload(PlacementResult.program))
        .order_by(PlacementResult.assigned_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise NoPlacementResult()

    return PlacementResultOut(
        id=row.id,
        user_id=row.user_id,
        attempt_id=row.attempt_id,
        program_id=row.program_id,
        program_code=row.program.code if row.program else None,
        program_title=row.program.title if row.program else None,
        level=row.level,
        is_override=row.is_override,
        assigned_at=row.assigned_at,
    )


async def list_placement_results(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 50,
    program_id: uuid.UUID | None = None,
) -> tuple[list[AdminPlacementResultOut], int]:
    """Return a paginated list of all placement results for admin review.

    Results are ordered by ``assigned_at`` descending (most recent first).
    ``raw_score``, ``max_score``, and ``score_percent`` are pulled from
    ``PlacementAttempt.meta`` when an attempt is associated with the result.

    Args:
        db: Active async database session.
        page: 1-based page number.
        size: Results per page.
        program_id: Optional — restrict results to a specific program.

    Returns:
        A ``(list[AdminPlacementResultOut], total)`` tuple.
    """
    offset = (page - 1) * size

    base = select(PlacementResult)
    if program_id is not None:
        base = base.where(PlacementResult.program_id == program_id)

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    result = await db.execute(
        base.options(
            selectinload(PlacementResult.user),
            selectinload(PlacementResult.program),
            selectinload(PlacementResult.attempt),
        )
        .order_by(PlacementResult.assigned_at.desc())
        .offset(offset)
        .limit(size)
    )
    rows = result.scalars().all()

    out = []
    for row in rows:
        meta = row.attempt.meta if row.attempt and row.attempt.meta else {}
        out.append(
            AdminPlacementResultOut(
                id=row.id,
                user_id=row.user_id,
                attempt_id=row.attempt_id,
                program_id=row.program_id,
                program_code=row.program.code if row.program else None,
                program_title=row.program.title if row.program else None,
                level=row.level,
                is_override=row.is_override,
                assigned_at=row.assigned_at,
                user_email=row.user.email,
                user_display_name=row.user.display_name or row.user.username,
                raw_score=row.attempt.score if row.attempt else None,
                max_score=meta.get("max_score"),
                score_percent=meta.get("score_percent"),
            )
        )
    return out, total


async def override_placement_result(
    db: AsyncSession, result_id: uuid.UUID, data: PlacementResultOverrideIn
) -> AdminPlacementResultOut:
    """Override a placement result with an admin-assigned program and level.

    Updates the ``PlacementResult`` row in place and swaps the student's active
    ``ProgramEnrollment`` to match.  The original attempt data is preserved.

    Args:
        db: Active async database session.
        result_id: UUID of the ``PlacementResult`` to override.
        data: ``PlacementResultOverrideIn`` with the new program and level.

    Returns:
        An ``AdminPlacementResultOut`` reflecting the updated result.

    Raises:
        PlacementResultNotFound: When no result with ``result_id`` exists.
        ProgramNotFound: When ``data.program_id`` does not match any program.
    """
    result = await db.execute(
        select(PlacementResult)
        .where(PlacementResult.id == result_id)
        .options(
            selectinload(PlacementResult.user),
            selectinload(PlacementResult.program),
            selectinload(PlacementResult.attempt),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise PlacementResultNotFound()

    prog_result = await db.execute(
        select(Program).where(Program.id == data.program_id)
    )
    program = prog_result.scalar_one_or_none()
    if program is None:
        raise ProgramNotFound()

    row.program_id = program.id
    row.level = data.level
    row.is_override = True

    await _swap_program_enrollment(db, row.user_id, program.id)
    await db.commit()
    await db.refresh(row)

    # Reload relationships after commit
    result2 = await db.execute(
        select(PlacementResult)
        .where(PlacementResult.id == result_id)
        .options(
            selectinload(PlacementResult.user),
            selectinload(PlacementResult.program),
            selectinload(PlacementResult.attempt),
        )
    )
    row = result2.scalar_one()

    meta = row.attempt.meta if row.attempt and row.attempt.meta else {}
    return AdminPlacementResultOut(
        id=row.id,
        user_id=row.user_id,
        attempt_id=row.attempt_id,
        program_id=row.program_id,
        program_code=row.program.code if row.program else None,
        program_title=row.program.title if row.program else None,
        level=row.level,
        is_override=row.is_override,
        assigned_at=row.assigned_at,
        user_email=row.user.email,
        user_display_name=row.user.display_name or row.user.username,
        raw_score=row.attempt.score if row.attempt else None,
        max_score=meta.get("max_score"),
        score_percent=meta.get("score_percent"),
    )
