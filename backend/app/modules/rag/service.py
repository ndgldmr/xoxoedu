"""Business logic for the RAG course assistant.

Pipeline for each query:
1. Enrollment gate — student must be active/completed in the course.
2. Rate limit — 20 queries per student per hour per course (Redis).
3. Load or create conversation (unique per user+course).
4. Load last 8 turns of history for LLM context.
5. Embed the question via OpenAI text-embedding-3-small.
6. Cosine ANN search in lesson_chunks scoped strictly to course_id.
7. Build system prompt from retrieved chunks via Jinja2 template.
8. Call LLM via the shared LLMClient (retry + circuit breaker included).
9. Persist user message + assistant reply in a single DB transaction.
10. Enqueue async AI usage log.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator

import openai
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import AssistantRateLimited, NotEnrolled
from app.core.redis import get_redis
from app.db.models.assistant import Conversation, ConversationMessage
from app.db.models.course import Lesson
from app.db.models.enrollment import Enrollment
from app.db.models.rag import LessonChunk
from app.modules.ai.client import llm_client
from app.modules.ai.service import render_prompt
from app.modules.ai.tasks import log_ai_usage
from app.modules.rag.schemas import AssistantResponse, CitationOut, ConversationOut, MessageOut

# ── Constants ──────────────────────────────────────────────────────────────────

_RATE_LIMIT_MAX = 20
_RATE_LIMIT_WINDOW_SECS = 3600
_HISTORY_TURNS = 8      # number of back-and-forth turns to include
_TOP_K_CHUNKS = 5       # retrieved context chunks per query
_EMBEDDING_MODEL = "text-embedding-3-small"


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _check_enrollment(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> None:
    """Raise ``NotEnrolled`` if the student has no active/completed enrollment."""
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
            Enrollment.status.in_(["active", "completed"]),
        )
    )
    if not enrollment:
        raise NotEnrolled()


async def _check_rate_limit(
    user_id: uuid.UUID, course_id: uuid.UUID
) -> None:
    """Increment the per-hour query counter; raise ``AssistantRateLimited`` if exceeded.

    Key format: ``rate:assistant:{user_id}:{course_id}:{hour_bucket}``
    The hour bucket rolls over every 3600 seconds so old keys expire naturally.
    """
    redis = get_redis()
    hour_bucket = int(time.time() // _RATE_LIMIT_WINDOW_SECS)
    key = f"rate:assistant:{user_id}:{course_id}:{hour_bucket}"
    count = await redis.incr(key)
    if count == 1:
        # Set expiry only on the first increment so the window is exactly 1 hour.
        await redis.expire(key, _RATE_LIMIT_WINDOW_SECS)
    if count > _RATE_LIMIT_MAX:
        raise AssistantRateLimited()


async def _get_or_create_conversation(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID
) -> Conversation:
    """Return the existing conversation for this student+course, creating one if absent."""
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.course_id == course_id,
        )
    )
    if not conversation:
        conversation = Conversation(user_id=user_id, course_id=course_id)
        db.add(conversation)
        await db.flush()
    return conversation


async def _load_history(
    db: AsyncSession, conversation_id: uuid.UUID
) -> list[dict[str, str]]:
    """Return the last ``_HISTORY_TURNS`` turns as an OpenAI-style message list.

    Fetches newest-first (cheap indexed query), then reverses to give the LLM
    chronological context.
    """
    rows = await db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(_HISTORY_TURNS * 2)  # 2 messages per turn (user + assistant)
    )
    messages = list(reversed(list(rows.all())))
    return [{"role": m.role, "content": m.content} for m in messages]


async def _embed(question: str) -> list[float]:
    """Embed a single query string using the OpenAI embeddings API."""
    client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.embeddings.create(
        model=_EMBEDDING_MODEL,
        input=[question],
    )
    return response.data[0].embedding


async def _retrieve_chunks(
    db: AsyncSession, course_id: uuid.UUID, embedding: list[float]
) -> list[LessonChunk]:
    """Run a cosine ANN search against lesson_chunks, scoped strictly to course_id.

    The ``course_id`` filter is always applied first so that a student of
    course A can never receive content from course B, regardless of embedding
    similarity.
    """
    rows = await db.scalars(
        select(LessonChunk)
        .where(LessonChunk.course_id == course_id)
        .order_by(LessonChunk.embedding.cosine_distance(embedding))
        .limit(_TOP_K_CHUNKS)
    )
    return list(rows.all())


# ── Public API ─────────────────────────────────────────────────────────────────

async def ask(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    question: str,
) -> AssistantResponse:
    """Run the full RAG query pipeline and return the assistant's response.

    Args:
        db: Async database session.
        user_id: UUID of the authenticated student.
        course_id: UUID of the course the student is asking about.
        question: The student's question text.

    Returns:
        ``AssistantResponse`` containing the conversation ID, the assistant
        reply, and the lesson IDs whose chunks were retrieved.

    Raises:
        NotEnrolled: If the student is not actively enrolled in the course.
        AssistantRateLimited: If the student has exceeded 20 queries per hour.
        AIUnavailable: If the circuit breaker is open or all LLM retries fail.
    """
    await _check_enrollment(db, user_id, course_id)
    await _check_rate_limit(user_id, course_id)

    conversation = await _get_or_create_conversation(db, user_id, course_id)
    history = await _load_history(db, conversation.id)

    query_embedding = await _embed(question)
    chunks = await _retrieve_chunks(db, course_id, query_embedding)

    # Resolve lesson titles for the prompt (one query for all chunks)
    lesson_ids = list({c.lesson_id for c in chunks})
    lesson_titles: dict[uuid.UUID, str] = {}
    if lesson_ids:
        rows = await db.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids)))
        lesson_titles = {ls.id: ls.title for ls in rows.all()}

    chunk_contexts = [
        {
            "lesson_title": lesson_titles.get(c.lesson_id, "Course Material"),
            "body": c.body,
        }
        for c in chunks
    ]

    # Build OpenAI-style messages: system + history + current question
    system_msg = render_prompt("rag_assistant.j2", chunks=chunk_contexts)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_msg}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    llm_response = await llm_client.complete(messages, temperature=0.3)

    # Persist both turns atomically
    user_message = ConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=question,
    )
    assistant_message = ConversationMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=llm_response.content,
    )
    db.add(user_message)
    db.add(assistant_message)
    await db.commit()
    await db.refresh(assistant_message)

    # Fire-and-forget usage log
    if llm_response.tokens_in > 0 or llm_response.tokens_out > 0:
        log_ai_usage.delay(
            user_id=str(user_id),
            course_id=str(course_id),
            feature="rag_assistant",
            tokens_in=llm_response.tokens_in,
            tokens_out=llm_response.tokens_out,
            model=llm_response.model,
        )

    return AssistantResponse(
        conversation_id=conversation.id,
        message=MessageOut.model_validate(assistant_message),
        retrieved_lesson_ids=list({c.lesson_id for c in chunks}),
    )


def build_citations(
    chunks: list[LessonChunk],
    lesson_titles: dict[uuid.UUID, str],
) -> list[CitationOut]:
    """Build a deduplicated, ordered list of citation objects from retrieved chunks.

    Deduplicates by ``lesson_id`` — if multiple chunks came from the same
    lesson, only one citation is emitted (preserving first-seen order).

    Args:
        chunks: Retrieved ``LessonChunk`` rows, in retrieval rank order.
        lesson_titles: Map of ``lesson_id → title`` from the DB lookup.

    Returns:
        Ordered list of ``CitationOut`` with no duplicate ``lesson_id`` values.
    """
    seen: set[uuid.UUID] = set()
    citations: list[CitationOut] = []
    for chunk in chunks:
        if chunk.lesson_id not in seen:
            seen.add(chunk.lesson_id)
            citations.append(
                CitationOut(
                    lesson_id=chunk.lesson_id,
                    lesson_title=lesson_titles.get(chunk.lesson_id, "Course Material"),
                    source=chunk.source,
                )
            )
    return citations


async def ask_stream(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    conversation_id: uuid.UUID,
    question: str,
) -> AsyncGenerator[dict, None]:
    """Run the RAG pipeline and yield SSE event dicts for streaming delivery.

    Performs the same pre-flight checks and retrieval as ``ask()``, then streams
    LLM tokens as ``{"data": '{"token": "..."}'}`` events.  After the model
    finishes, emits a ``citations`` event and a ``done`` event.  Both message
    turns are persisted in a single commit after the stream completes.

    The caller wraps the return value in ``EventSourceResponse``.  Each yielded
    dict is an SSE event with optional ``event`` and ``data`` keys.

    Args:
        db: Async database session.
        user_id: UUID of the authenticated student.
        course_id: UUID of the course the student is asking about.
        conversation_id: UUID of the existing conversation to continue.
        question: The student's question text.

    Yields:
        Dicts consumed by ``EventSourceResponse``:
        - ``{"data": '{"token": "<delta>"}'}`` — one per content delta
        - ``{"event": "citations", "data": "<json>"}`` — citation block
        - ``{"event": "done", "data": "{}"}`` — terminal sentinel

    Raises:
        NotEnrolled: If the student is not enrolled.
        ConversationNotFound: If ``conversation_id`` does not belong to this
            student and course.
        AssistantRateLimited: If the per-hour quota is exceeded.
        AIUnavailable: If the circuit breaker is open.
    """
    from app.core.exceptions import ConversationNotFound

    await _check_enrollment(db, user_id, course_id)
    await _check_rate_limit(user_id, course_id)

    # Verify the conversation belongs to this student+course.
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.course_id == course_id,
        )
    )
    if not conversation:
        raise ConversationNotFound()

    history = await _load_history(db, conversation.id)
    query_embedding = await _embed(question)
    chunks = await _retrieve_chunks(db, course_id, query_embedding)

    lesson_ids = list({c.lesson_id for c in chunks})
    lesson_titles: dict[uuid.UUID, str] = {}
    if lesson_ids:
        rows = await db.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids)))
        lesson_titles = {ls.id: ls.title for ls in rows.all()}

    chunk_contexts = [
        {"lesson_title": lesson_titles.get(c.lesson_id, "Course Material"), "body": c.body}
        for c in chunks
    ]

    system_msg = render_prompt("rag_assistant.j2", chunks=chunk_contexts)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_msg}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    citations = build_citations(chunks, lesson_titles)

    async def _generate() -> AsyncGenerator[dict, None]:
        buffer: list[str] = []
        try:
            async for token in llm_client.stream(messages, temperature=0.3):
                buffer.append(token)
                yield {"data": json.dumps({"token": token})}

            full_content = "".join(buffer)

            # Persist both turns after stream completes.
            db.add(ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content=question,
            ))
            db.add(ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=full_content,
            ))
            await db.commit()

        finally:
            # Always emit citations + done, even if the stream is cut short.
            yield {
                "event": "citations",
                "data": json.dumps({"citations": [c.model_dump(mode="json") for c in citations]}),
            }
            yield {"event": "done", "data": "{}"}

    return _generate()


async def list_conversations(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
) -> list[ConversationOut]:
    """Return the student's conversations, optionally filtered by course.

    Args:
        db: Async database session.
        user_id: UUID of the authenticated student.
        course_id: If provided, restrict results to this course.

    Returns:
        List of ``ConversationOut``, most recently updated first, each
        including the last message in the conversation.
    """
    query = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    if course_id is not None:
        query = query.where(Conversation.course_id == course_id)

    rows = await db.scalars(query)
    conversations = list(rows.all())

    result: list[ConversationOut] = []
    for conv in conversations:
        last_msg = await db.scalar(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(1)
        )
        result.append(
            ConversationOut(
                id=conv.id,
                course_id=conv.course_id,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                last_message=MessageOut.model_validate(last_msg) if last_msg else None,
            )
        )
    return result
