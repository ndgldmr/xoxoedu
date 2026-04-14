"""Business logic for quiz creation, retrieval, and submission scoring."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import MaxAttemptsExceeded, QuizNotFound, QuizSubmissionNotFound
from app.db.models.ai import AIUsageBudget
from app.db.models.course import Chapter, Lesson
from app.db.models.quiz import Quiz, QuizQuestion, QuizSubmission
from app.modules.quizzes.schemas import (
    OptionItem,
    QuizFeedbackOut,
    QuizIn,
    QuizOut,
    QuizQuestionOut,
    QuizSubmissionOut,
    SubmitQuizIn,
)

# ── Pure scoring helpers ───────────────────────────────────────────────────────

def _score_single_choice(correct: list[str], given: list[str], points: int) -> int:
    """Return ``points`` when exactly one correct option is selected, else ``0``.

    For single-choice questions selecting multiple options is treated as wrong,
    even if one of the selections happens to be correct.

    Args:
        correct: List containing the single correct option ID.
        given: Option IDs submitted by the student.
        points: Points awarded for a fully correct response.

    Returns:
        ``points`` on a correct single selection; ``0`` otherwise.
    """
    if len(given) == 1 and given[0] in correct:
        return points
    return 0


def _score_multi_choice(correct: list[str], given: list[str], points: int) -> int:
    """Return ``points`` only when ``given`` exactly matches ``correct``, else ``0``.

    Partial credit is not awarded — the student must select all correct options
    and no incorrect ones.

    Args:
        correct: All option IDs required for a fully correct response.
        given: Option IDs submitted by the student.
        points: Points awarded for a fully correct response.

    Returns:
        ``points`` on an exact match; ``0`` otherwise.
    """
    if set(given) == set(correct):
        return points
    return 0


def _score_submission(
    questions: list[QuizQuestion], answers: dict[str, list[str]]
) -> tuple[int, int]:
    """Compute the total score for one submission attempt.

    Args:
        questions: All ``QuizQuestion`` rows for the quiz.
        answers: ``{question_id: [option_ids]}`` mapping from the student.

    Returns:
        A ``(score, max_score)`` tuple where both values are non-negative integers.
    """
    score = 0
    max_score = 0
    for q in questions:
        max_score += q.points
        given = answers.get(str(q.id), [])
        if q.kind == "single_choice":
            score += _score_single_choice(q.correct_answers, given, q.points)
        else:
            score += _score_multi_choice(q.correct_answers, given, q.points)
    return score, max_score


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_question_out(q: QuizQuestion, *, reveal: bool) -> QuizQuestionOut:
    """Serialise a ``QuizQuestion`` ORM row into a ``QuizQuestionOut`` schema.

    Args:
        q: The ``QuizQuestion`` ORM instance to serialise.
        reveal: When ``True`` the ``correct_answers`` field is populated;
            when ``False`` it is masked to an empty list.

    Returns:
        A ``QuizQuestionOut`` ready for inclusion in an API response.
    """
    return QuizQuestionOut(
        id=q.id,
        position=q.position,
        kind=q.kind,
        stem=q.stem,
        options=[OptionItem(**opt) for opt in q.options],
        correct_answers=q.correct_answers if reveal else [],
        points=q.points,
    )


async def _load_quiz(db: AsyncSession, quiz_id: uuid.UUID) -> Quiz:
    """Load a ``Quiz`` with its ``questions`` eagerly loaded.

    Args:
        db: Active async database session.
        quiz_id: UUID of the quiz to load.

    Returns:
        The ``Quiz`` ORM instance with questions populated.

    Raises:
        QuizNotFound: When no quiz with ``quiz_id`` exists.
    """
    result = await db.execute(
        select(Quiz)
        .where(Quiz.id == quiz_id)
        .options(selectinload(Quiz.questions))
    )
    quiz = result.scalar_one_or_none()
    if quiz is None:
        raise QuizNotFound()
    return quiz


# ── Public service functions ───────────────────────────────────────────────────

async def create_quiz(db: AsyncSession, data: QuizIn) -> QuizOut:
    """Create a quiz with its questions in a single transaction.

    Args:
        db: Active async database session.
        data: Validated ``QuizIn`` payload from the request.

    Returns:
        A ``QuizOut`` representing the newly created quiz.
    """
    quiz = Quiz(
        lesson_id=data.lesson_id,
        title=data.title,
        description=data.description,
        max_attempts=data.max_attempts,
        time_limit_minutes=data.time_limit_minutes,
    )
    db.add(quiz)
    await db.flush()

    for q_in in data.questions:
        db.add(
            QuizQuestion(
                quiz_id=quiz.id,
                position=q_in.position,
                kind=q_in.kind,
                stem=q_in.stem,
                options=[opt.model_dump() for opt in q_in.options],
                correct_answers=q_in.correct_answers,
                points=q_in.points,
            )
        )

    await db.commit()
    await db.refresh(quiz)

    # Re-load with questions so the relationship is populated
    loaded = await _load_quiz(db, quiz.id)
    return QuizOut(
        id=loaded.id,
        lesson_id=loaded.lesson_id,
        title=loaded.title,
        description=loaded.description,
        max_attempts=loaded.max_attempts,
        time_limit_minutes=loaded.time_limit_minutes,
        questions=[_build_question_out(q, reveal=False) for q in loaded.questions],
    )


async def get_quiz_by_lesson(db: AsyncSession, lesson_id: uuid.UUID) -> QuizOut:
    """Return the quiz attached to a lesson (answers masked).

    Args:
        db: Active async database session.
        lesson_id: UUID of the lesson whose quiz is requested.

    Returns:
        A ``QuizOut`` with questions and correct answers masked.

    Raises:
        QuizNotFound: When no quiz exists for ``lesson_id``.
    """
    result = await db.execute(
        select(Quiz)
        .where(Quiz.lesson_id == lesson_id)
        .options(selectinload(Quiz.questions))
    )
    quiz = result.scalar_one_or_none()
    if quiz is None:
        raise QuizNotFound()
    return QuizOut(
        id=quiz.id,
        lesson_id=quiz.lesson_id,
        title=quiz.title,
        description=quiz.description,
        max_attempts=quiz.max_attempts,
        time_limit_minutes=quiz.time_limit_minutes,
        questions=[_build_question_out(q, reveal=False) for q in quiz.questions],
    )


async def get_quiz(db: AsyncSession, quiz_id: uuid.UUID, *, reveal: bool = False) -> QuizOut:
    """Return a quiz, optionally with correct answers revealed.

    Args:
        db: Active async database session.
        quiz_id: UUID of the quiz to retrieve.
        reveal: When ``True`` correct answers are included in the response.

    Returns:
        A ``QuizOut`` with questions, answers masked unless ``reveal=True``.

    Raises:
        QuizNotFound: When no quiz with ``quiz_id`` exists.
    """
    quiz = await _load_quiz(db, quiz_id)
    return QuizOut(
        id=quiz.id,
        lesson_id=quiz.lesson_id,
        title=quiz.title,
        description=quiz.description,
        max_attempts=quiz.max_attempts,
        time_limit_minutes=quiz.time_limit_minutes,
        questions=[_build_question_out(q, reveal=reveal) for q in quiz.questions],
    )


async def submit_quiz(
    db: AsyncSession, user_id: uuid.UUID, quiz_id: uuid.UUID, data: SubmitQuizIn
) -> QuizSubmissionOut:
    """Submit one quiz attempt and return the scored result.

    Counts existing attempts before inserting; raises ``MaxAttemptsExceeded``
    when the student has used all allowed attempts.  The ``UniqueConstraint``
    on ``(user_id, quiz_id, attempt_number)`` acts as a secondary TOCTOU guard
    — concurrent duplicate submissions raise ``IntegrityError`` which is also
    converted to ``MaxAttemptsExceeded``.

    Correct answers are revealed in the response when this attempt exhausts the
    student's remaining attempts.

    Args:
        db: Active async database session.
        user_id: UUID of the submitting student.
        quiz_id: UUID of the quiz being attempted.
        data: ``SubmitQuizIn`` containing the student's answers.

    Returns:
        A ``QuizSubmissionOut`` with the scored result and optionally revealed answers.

    Raises:
        QuizNotFound: When no quiz with ``quiz_id`` exists.
        MaxAttemptsExceeded: When the student has no attempts remaining.
    """
    quiz = await _load_quiz(db, quiz_id)

    # Count existing attempts
    count_result = await db.execute(
        select(func.count()).where(
            QuizSubmission.user_id == user_id,
            QuizSubmission.quiz_id == quiz_id,
        )
    )
    attempts_used: int = count_result.scalar_one()

    if attempts_used >= quiz.max_attempts:
        raise MaxAttemptsExceeded()

    score, max_score = _score_submission(quiz.questions, data.answers)
    passed = score == max_score

    submission = QuizSubmission(
        user_id=user_id,
        quiz_id=quiz_id,
        attempt_number=attempts_used + 1,
        answers=data.answers,
        score=score,
        max_score=max_score,
        passed=passed,
    )
    db.add(submission)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise MaxAttemptsExceeded() from None

    await db.refresh(submission)

    # Enqueue AI feedback if the course has AI enabled
    course_id = await db.scalar(
        select(Chapter.course_id)
        .join(Lesson, Lesson.chapter_id == Chapter.id)
        .join(Quiz, Quiz.lesson_id == Lesson.id)
        .where(Quiz.id == quiz_id)
    )
    if course_id is not None:
        ai_config = await db.scalar(
            select(AIUsageBudget).where(AIUsageBudget.course_id == course_id)
        )
        ai_enabled = ai_config.ai_enabled if ai_config is not None else True
        if ai_enabled:
            from app.modules.ai.tasks import generate_quiz_feedback
            generate_quiz_feedback.delay(str(submission.id))

    # Reveal answers on the final attempt
    reveal = (attempts_used + 1) >= quiz.max_attempts
    return QuizSubmissionOut(
        id=submission.id,
        quiz_id=submission.quiz_id,
        attempt_number=submission.attempt_number,
        score=submission.score,
        max_score=submission.max_score,
        passed=submission.passed,
        submitted_at=submission.submitted_at,
        questions=[_build_question_out(q, reveal=reveal) for q in quiz.questions],
    )


async def list_submissions(
    db: AsyncSession, user_id: uuid.UUID, quiz_id: uuid.UUID
) -> list[QuizSubmissionOut]:
    """Return all submissions for a student on a specific quiz.

    Args:
        db: Active async database session.
        user_id: UUID of the student.
        quiz_id: UUID of the quiz.

    Returns:
        A list of ``QuizSubmissionOut`` ordered by ``attempt_number``.

    Raises:
        QuizNotFound: When no quiz with ``quiz_id`` exists.
    """
    quiz = await _load_quiz(db, quiz_id)

    result = await db.execute(
        select(QuizSubmission)
        .where(
            QuizSubmission.user_id == user_id,
            QuizSubmission.quiz_id == quiz_id,
        )
        .options(selectinload(QuizSubmission.ai_feedback))
        .order_by(QuizSubmission.attempt_number)
    )
    submissions = result.scalars().all()

    # Answers are revealed on any submission if attempts are exhausted
    reveal = len(submissions) >= quiz.max_attempts
    return [
        QuizSubmissionOut(
            id=s.id,
            quiz_id=s.quiz_id,
            attempt_number=s.attempt_number,
            score=s.score,
            max_score=s.max_score,
            passed=s.passed,
            submitted_at=s.submitted_at,
            questions=[_build_question_out(q, reveal=reveal) for q in quiz.questions],
            ai_feedback=[QuizFeedbackOut.model_validate(fb) for fb in s.ai_feedback],
        )
        for s in submissions
    ]


async def get_submission(
    db: AsyncSession, user_id: uuid.UUID, submission_id: uuid.UUID
) -> QuizSubmissionOut:
    """Return a single quiz submission belonging to the requesting student.

    Args:
        db: Active async database session.
        user_id: UUID of the requesting student; used to scope access.
        submission_id: UUID of the submission to retrieve.

    Returns:
        A ``QuizSubmissionOut`` for the requested submission.

    Raises:
        QuizSubmissionNotFound: When no matching submission exists for this student.
    """
    result = await db.execute(
        select(QuizSubmission)
        .where(
            QuizSubmission.id == submission_id,
            QuizSubmission.user_id == user_id,
        )
        .options(selectinload(QuizSubmission.ai_feedback))
    )
    submission = result.scalar_one_or_none()
    if submission is None:
        raise QuizSubmissionNotFound()

    quiz = await _load_quiz(db, submission.quiz_id)

    count_result = await db.execute(
        select(func.count()).where(
            QuizSubmission.user_id == user_id,
            QuizSubmission.quiz_id == submission.quiz_id,
        )
    )
    attempts_used: int = count_result.scalar_one()
    reveal = attempts_used >= quiz.max_attempts

    return QuizSubmissionOut(
        id=submission.id,
        quiz_id=submission.quiz_id,
        attempt_number=submission.attempt_number,
        score=submission.score,
        max_score=submission.max_score,
        passed=submission.passed,
        submitted_at=submission.submitted_at,
        questions=[_build_question_out(q, reveal=reveal) for q in quiz.questions],
        ai_feedback=[QuizFeedbackOut.model_validate(fb) for fb in submission.ai_feedback],
    )
