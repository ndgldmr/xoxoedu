"""FastAPI router for the RAG course assistant endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies import get_current_verified_user
from app.modules.rag import service
from app.modules.rag.schemas import AssistantRequest

router = APIRouter(tags=["assistant"])


@router.post("/courses/{course_id}/assistant")
async def ask_assistant(
    course_id: uuid.UUID,
    body: AssistantRequest,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ask the course AI assistant a question.

    Creates a conversation for this student+course pair on first call and
    continues it on subsequent calls.  The response always includes the full
    assistant reply and the lesson IDs that contributed context.

    Args:
        course_id: UUID of the course to query.
        body: Request body containing the student's question.
        current_user: Authenticated, verified student.
        db: Database session.

    Returns:
        ``AssistantResponse`` wrapped in the standard response envelope.

    Raises:
        NotEnrolled: 403 if the student is not enrolled in this course.
        AssistantRateLimited: 429 if the student has exceeded 20 queries/hour.
        AIUnavailable: 503 if the LLM provider is unreachable.
    """
    result = await service.ask(
        db=db,
        user_id=current_user.id,
        course_id=course_id,
        question=body.question,
    )
    return ok(result.model_dump())


@router.get("/assistant/conversations/{conversation_id}/stream")
async def stream_assistant(
    conversation_id: uuid.UUID,
    question: str = Query(..., min_length=1, max_length=2000),
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """Stream an assistant response token-by-token via Server-Sent Events.

    Runs the same RAG pipeline as the non-streaming POST endpoint but flushes
    each LLM token as it arrives.  The ``course_id`` is resolved from the
    conversation record so the client only needs the ``conversation_id``.

    Event protocol:
    - ``data: {"token": "..."}`` — one per content delta
    - ``event: citations`` with ``data: {"citations": [...]}`` — source block
    - ``event: done`` with ``data: {}`` — terminal sentinel

    Args:
        conversation_id: UUID of the conversation to continue.
        question: The student's question (passed as a query parameter).
        current_user: Authenticated, verified student.
        db: Database session.

    Returns:
        ``EventSourceResponse`` wrapping the async token generator.

    Raises:
        NotEnrolled: 403 if the student is not enrolled in the conversation's course.
        ConversationNotFound: 404 if the conversation doesn't exist or belong to the student.
        AssistantRateLimited: 429 if the per-hour quota is exceeded.
        AIUnavailable: 503 if the LLM provider is unreachable.
    """
    from sqlalchemy import select

    from app.core.exceptions import ConversationNotFound
    from app.db.models.assistant import Conversation

    # Resolve course_id from the conversation so the service can gate on it.
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if not conv:
        raise ConversationNotFound()

    generator = await service.ask_stream(
        db=db,
        user_id=current_user.id,
        course_id=conv.course_id,
        conversation_id=conversation_id,
        question=question,
    )
    return EventSourceResponse(generator)


@router.get("/assistant/conversations")
async def list_conversations(
    course_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the student's assistant conversations, optionally filtered by course.

    Args:
        course_id: Optional course UUID to filter results.
        current_user: Authenticated, verified student.
        db: Database session.

    Returns:
        List of ``ConversationOut`` wrapped in the standard response envelope,
        most recently updated first.
    """
    conversations = await service.list_conversations(
        db=db,
        user_id=current_user.id,
        course_id=course_id,
    )
    return ok([c.model_dump() for c in conversations])
