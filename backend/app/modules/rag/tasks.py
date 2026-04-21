"""Celery task for indexing lesson content into pgvector for RAG retrieval."""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.retry import indexing_backoff

# ── Chunking ───────────────────────────────────────────────────────────────────

_CHUNK_SIZE = 1500   # characters (~375 tokens for English prose)
_CHUNK_OVERLAP = 200  # characters shared between adjacent chunks


def _chunk_text(text: str) -> list[str]:
    """Split *text* into overlapping fixed-size character windows.

    Uses a sliding window rather than hard splits so that sentences near a
    boundary appear fully in at least one chunk.

    Args:
        text: The plain-text string to split.

    Returns:
        Ordered list of chunk strings.  Returns an empty list for blank input.
    """
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return chunks


def _extract_text(content: dict) -> str:
    """Recursively extract all string values from a JSONB content blob.

    The lesson ``content`` field has no enforced schema — its shape varies by
    editor and lesson type.  Walking the tree and concatenating all strings
    (skipping very short values like UI labels) is more resilient than
    assuming a specific key layout.

    Args:
        content: Arbitrary dict loaded from the lessons.content JSONB column.

    Returns:
        A single whitespace-joined string of all extracted text.
    """
    parts: list[str] = []

    def _walk(node: object) -> None:
        if isinstance(node, str):
            stripped = node.strip()
            # Skip very short strings — likely field names, icons, or IDs
            if len(stripped) > 20:
                parts.append(stripped)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(content)
    return " ".join(parts)


# ── Main task ──────────────────────────────────────────────────────────────────

@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=3,
    soft_time_limit=150,
    time_limit=180,
)
def index_lesson(self, lesson_id: str) -> None:
    """Chunk and embed a lesson's text content, storing vectors in lesson_chunks.

    Indexes two sources when available:
    - ``"content"``: the JSONB body of a text-type lesson.
    - ``"transcript"``: the plain-text transcript of a video lesson.

    The task is idempotent: existing chunks for the lesson are deleted before
    the new set is inserted, so re-triggering always produces a clean result.

    Steps:
    1. Load the lesson (+ its chapter to resolve course_id) and transcript.
    2. Extract and chunk text from each available source.
    3. Batch-embed all chunks in a single OpenAI API call.
    4. Delete old chunks, insert new rows.

    Retries up to 3 times with exponential backoff (30 s → 60 s → 120 s) on
    transient DB or API failures.

    Args:
        lesson_id: String UUID of the ``Lesson`` to index.
    """
    try:
        import uuid as _uuid

        import openai
        from sqlalchemy import create_engine, delete, select
        from sqlalchemy.orm import Session, joinedload

        from app.config import settings
        from app.db.models.course import Chapter, Lesson, LessonTranscript
        from app.db.models.rag import LessonChunk

        lesson_uuid = _uuid.UUID(lesson_id)
        engine = create_engine(settings.DATABASE_URL_SYNC)

        with Session(engine) as db:
            # Load lesson with chapter so we can resolve course_id without an
            # extra query.
            lesson = db.execute(
                select(Lesson)
                .options(joinedload(Lesson.chapter))
                .where(Lesson.id == lesson_uuid)
            ).unique().scalar_one_or_none()

            if lesson is None:
                return

            course_id: _uuid.UUID = lesson.chapter.course_id

            # ── Collect text sources ───────────────────────────────────────────

            # List of (source_label, text) pairs to index.
            sources: list[tuple[str, str]] = []

            if lesson.type == "text" and lesson.content:
                body = _extract_text(lesson.content)
                if body:
                    sources.append(("content", body))

            transcript = db.execute(
                select(LessonTranscript).where(
                    LessonTranscript.lesson_id == lesson_uuid
                )
            ).scalar_one_or_none()

            if transcript and transcript.plain_text.strip():
                sources.append(("transcript", transcript.plain_text))

            if not sources:
                # Nothing to index (e.g. video lesson with no transcript yet).
                return

            # ── Chunk all sources ──────────────────────────────────────────────

            # Build a flat list of (source, chunk_index, body) tuples.
            # chunk_index is per-lesson, counting across sources in order.
            pending: list[tuple[str, int, str]] = []
            global_idx = 0
            for source_label, text in sources:
                for chunk_body in _chunk_text(text):
                    pending.append((source_label, global_idx, chunk_body))
                    global_idx += 1

            if not pending:
                return

            # ── Embed all chunks in a single API call ──────────────────────────

            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=[body for _, _, body in pending],
            )
            # The API returns embeddings in the same order as the input list.
            embeddings: list[list[float]] = [item.embedding for item in response.data]

            # ── Upsert: delete old, insert new ─────────────────────────────────

            db.execute(
                delete(LessonChunk).where(LessonChunk.lesson_id == lesson_uuid)
            )

            for (source_label, chunk_index, chunk_body), embedding in zip(pending, embeddings):
                db.add(
                    LessonChunk(
                        lesson_id=lesson_uuid,
                        course_id=course_id,
                        chunk_index=chunk_index,
                        source=source_label,
                        body=chunk_body,
                        embedding=embedding,
                    )
                )

            db.commit()

    except Exception as exc:
        raise self.retry(exc=exc, countdown=indexing_backoff(self.request.retries)) from exc
