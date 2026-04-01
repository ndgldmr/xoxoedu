"""API router for quiz retrieval and submission (student-facing endpoints)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.session import get_db
from app.modules.quizzes import service
from app.modules.quizzes.schemas import SubmitQuizIn

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


@router.get("/submissions/{submission_id}")
async def get_submission(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=require_role(Role.STUDENT),
) -> dict:
    """Retrieve a single quiz submission belonging to the current student.

    Args:
        submission_id: UUID of the submission to retrieve.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        The ``QuizSubmissionOut`` wrapped in the standard response envelope.
    """
    submission = await service.get_submission(db, current_user.id, submission_id)
    return ok(submission.model_dump())


@router.get("/{quiz_id}")
async def get_quiz(
    quiz_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=require_role(Role.STUDENT),
) -> dict:
    """Retrieve a quiz with questions (correct answers masked).

    Args:
        quiz_id: UUID of the quiz to retrieve.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        The ``QuizOut`` wrapped in the standard response envelope.
    """
    quiz = await service.get_quiz(db, quiz_id)
    return ok(quiz.model_dump())


@router.post("/{quiz_id}/submit", status_code=201)
async def submit_quiz(
    quiz_id: uuid.UUID,
    data: SubmitQuizIn,
    db: AsyncSession = Depends(get_db),
    current_user=require_role(Role.STUDENT),
) -> dict:
    """Submit one attempt at a quiz.

    Correct answers are revealed in the response when this submission
    exhausts the student's remaining attempts.

    Args:
        quiz_id: UUID of the quiz to attempt.
        data: The student's answers.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        A ``QuizSubmissionOut`` with scoring and optionally revealed answers.
    """
    submission = await service.submit_quiz(db, current_user.id, quiz_id, data)
    return ok(submission.model_dump())


@router.get("/{quiz_id}/submissions")
async def list_submissions(
    quiz_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=require_role(Role.STUDENT),
) -> dict:
    """List all submissions made by the current student on a quiz.

    Args:
        quiz_id: UUID of the quiz.
        db: Injected async database session.
        current_user: Authenticated student from the JWT.

    Returns:
        A list of ``QuizSubmissionOut`` wrapped in the standard response envelope.
    """
    submissions = await service.list_submissions(db, current_user.id, quiz_id)
    return ok([s.model_dump() for s in submissions])
