"""API router for quiz retrieval, submission, and admin quiz management."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.modules.quizzes import service
from app.modules.quizzes.schemas import QuizIn, QuizUpdateIn, SubmitQuizIn

router = APIRouter(tags=["quizzes"])
admin_router = APIRouter(prefix="/admin", tags=["quizzes"], dependencies=[require_role(Role.ADMIN)])


@router.get("/quizzes/submissions/{submission_id}")
async def get_submission(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Retrieve a single quiz submission belonging to the current student."""
    submission = await service.get_submission(db, current_user.id, submission_id)
    return ok(submission.model_dump())


@router.get("/lessons/{lesson_id}/quiz")
async def get_quiz_by_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Retrieve the quiz for a lesson by ``lesson_id`` with answers masked."""
    quiz = await service.get_quiz_by_lesson(db, lesson_id)
    return ok(quiz.model_dump())


@router.get("/quizzes/{quiz_id}")
async def get_quiz(
    quiz_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Retrieve a quiz with questions and masked correct answers."""
    quiz = await service.get_quiz(db, quiz_id)
    return ok(quiz.model_dump())


@router.post("/quizzes/{quiz_id}/submissions", status_code=201)
async def submit_quiz(
    quiz_id: uuid.UUID,
    data: SubmitQuizIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """Submit one quiz attempt for the authenticated student."""
    submission = await service.submit_quiz(db, current_user.id, quiz_id, data)
    return ok(submission.model_dump())


@router.get("/quizzes/{quiz_id}/submissions")
async def list_submissions(
    quiz_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_role(Role.STUDENT),
) -> dict:
    """List all submissions made by the current student on a quiz."""
    submissions = await service.list_submissions(db, current_user.id, quiz_id)
    return ok([s.model_dump() for s in submissions])


@admin_router.post("/quizzes", status_code=201)
async def create_quiz(
    data: QuizIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a quiz with questions on a lesson."""
    quiz = await service.create_quiz(db, data)
    return ok(quiz.model_dump())


@admin_router.get("/lessons/{lesson_id}/quiz")
async def get_quiz_admin(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch the admin quiz view for a lesson with answers revealed."""
    quiz = await service.get_quiz_by_lesson(db, lesson_id, reveal=True)
    return ok(quiz.model_dump())


@admin_router.patch("/quizzes/{quiz_id}")
async def update_quiz(
    quiz_id: uuid.UUID,
    data: QuizUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Replace a quiz's metadata and full question set."""
    quiz = await service.update_quiz(db, quiz_id, data)
    return ok(quiz.model_dump())


router.include_router(admin_router)
