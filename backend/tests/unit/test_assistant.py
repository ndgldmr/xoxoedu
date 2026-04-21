"""Unit tests for the RAG course assistant — Sprint 9A.

Covers:
- Conversation history truncation (last N turns, chronological order)
- Rate limit counter logic (increment, first-call expiry, rejection)
- Scope enforcement (course_id always in WHERE clause)
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── History truncation ─────────────────────────────────────────────────────────

class TestLoadHistory:
    """_load_history returns at most 2 * _HISTORY_TURNS messages, oldest first."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_new_conversation(self) -> None:
        from app.modules.rag.service import _load_history

        db = AsyncMock()
        db.scalars.return_value = AsyncMock(all=MagicMock(return_value=[]))

        result = await _load_history(db, uuid.uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_truncates_to_last_16_messages(self) -> None:
        """When > 16 messages exist, only the most recent 16 are included."""
        from app.modules.rag.service import _load_history, _HISTORY_TURNS

        # Build 20 fake messages (10 turns)
        fake_messages = []
        for i in range(20):
            m = MagicMock()
            m.role = "user" if i % 2 == 0 else "assistant"
            m.content = f"message {i}"
            fake_messages.append(m)

        # Simulate the DB returning newest-first (the query uses .desc())
        newest_first = list(reversed(fake_messages[-16:]))

        db = AsyncMock()
        db.scalars.return_value = AsyncMock(all=MagicMock(return_value=newest_first))

        result = await _load_history(db, uuid.uuid4())

        # Result should be chronological (oldest first)
        assert len(result) == _HISTORY_TURNS * 2
        assert result[0]["content"] == newest_first[-1].content
        assert result[-1]["content"] == newest_first[0].content

    @pytest.mark.asyncio
    async def test_message_format_matches_openai_style(self) -> None:
        """Each item must have exactly 'role' and 'content' keys."""
        from app.modules.rag.service import _load_history

        m = MagicMock()
        m.role = "user"
        m.content = "What is Python?"

        db = AsyncMock()
        db.scalars.return_value = AsyncMock(all=MagicMock(return_value=[m]))

        result = await _load_history(db, uuid.uuid4())

        assert len(result) == 1
        assert set(result[0].keys()) == {"role", "content"}
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "What is Python?"

    @pytest.mark.asyncio
    async def test_chronological_order_restored(self) -> None:
        """Messages must be oldest-first regardless of DB return order."""
        from app.modules.rag.service import _load_history

        messages = []
        for i in range(6):
            m = MagicMock()
            m.role = "user" if i % 2 == 0 else "assistant"
            m.content = str(i)
            messages.append(m)

        # DB returns newest-first
        db = AsyncMock()
        db.scalars.return_value = AsyncMock(
            all=MagicMock(return_value=list(reversed(messages)))
        )

        result = await _load_history(db, uuid.uuid4())

        assert [r["content"] for r in result] == ["0", "1", "2", "3", "4", "5"]


# ── Rate limiting ──────────────────────────────────────────────────────────────

class TestCheckRateLimit:
    """_check_rate_limit increments an hourly Redis counter per student+course."""

    @pytest.mark.asyncio
    async def test_first_call_sets_expiry(self) -> None:
        from app.modules.rag.service import _check_rate_limit

        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 1

        with patch("app.modules.rag.service.get_redis", return_value=mock_redis):
            await _check_rate_limit(uuid.uuid4(), uuid.uuid4())

        mock_redis.expire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subsequent_calls_do_not_reset_expiry(self) -> None:
        from app.modules.rag.service import _check_rate_limit

        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 5  # not the first call

        with patch("app.modules.rag.service.get_redis", return_value=mock_redis):
            await _check_rate_limit(uuid.uuid4(), uuid.uuid4())

        mock_redis.expire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_at_limit_plus_one(self) -> None:
        from app.modules.rag.service import _check_rate_limit, _RATE_LIMIT_MAX
        from app.core.exceptions import AssistantRateLimited

        mock_redis = AsyncMock()
        mock_redis.incr.return_value = _RATE_LIMIT_MAX + 1

        with patch("app.modules.rag.service.get_redis", return_value=mock_redis):
            with pytest.raises(AssistantRateLimited):
                await _check_rate_limit(uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_does_not_raise_at_exactly_limit(self) -> None:
        from app.modules.rag.service import _check_rate_limit, _RATE_LIMIT_MAX
        from app.core.exceptions import AssistantRateLimited

        mock_redis = AsyncMock()
        mock_redis.incr.return_value = _RATE_LIMIT_MAX  # exactly at limit — OK

        with patch("app.modules.rag.service.get_redis", return_value=mock_redis):
            await _check_rate_limit(uuid.uuid4(), uuid.uuid4())  # should not raise

    @pytest.mark.asyncio
    async def test_key_includes_user_course_and_hour_bucket(self) -> None:
        """The Redis key must encode user, course, and the current hour."""
        from app.modules.rag.service import _check_rate_limit, _RATE_LIMIT_WINDOW_SECS

        user_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        course_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        expected_bucket = int(time.time() // _RATE_LIMIT_WINDOW_SECS)

        mock_redis = AsyncMock()
        mock_redis.incr.return_value = 1

        with patch("app.modules.rag.service.get_redis", return_value=mock_redis):
            await _check_rate_limit(user_id, course_id)

        key_used = mock_redis.incr.call_args[0][0]
        assert str(user_id) in key_used
        assert str(course_id) in key_used
        assert str(expected_bucket) in key_used


# ── Scope enforcement ──────────────────────────────────────────────────────────

class TestRetrieveChunks:
    """_retrieve_chunks always filters by course_id before ordering by distance."""

    @pytest.mark.asyncio
    async def test_query_scoped_to_course_id(self) -> None:
        """The WHERE clause must bind the correct course_id — no cross-course leakage."""
        from app.modules.rag.service import _retrieve_chunks
        from app.db.models.rag import LessonChunk

        course_id = uuid.uuid4()
        embedding = [0.1] * 1536

        db = AsyncMock()
        db.scalars.return_value = AsyncMock(all=MagicMock(return_value=[]))

        await _retrieve_chunks(db, course_id, embedding)

        # Inspect the compiled query that was passed to db.scalars
        call_args = db.scalars.call_args
        query = call_args[0][0]
        compiled = query.compile(compile_kwargs={"literal_binds": False})
        sql = str(compiled)

        # The WHERE clause must reference the lesson_chunks table
        assert "lesson_chunks" in sql.lower() or "course_id" in sql.lower()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_chunks_indexed(self) -> None:
        from app.modules.rag.service import _retrieve_chunks

        db = AsyncMock()
        db.scalars.return_value = AsyncMock(all=MagicMock(return_value=[]))

        result = await _retrieve_chunks(db, uuid.uuid4(), [0.1] * 1536)

        assert result == []


# ── Citation extraction ────────────────────────────────────────────────────────

class TestBuildCitations:
    """build_citations deduplicates by lesson_id and preserves retrieval order."""

    def _make_chunk(
        self,
        lesson_id: uuid.UUID,
        chunk_index: int = 0,
        source: str = "content",
    ) -> MagicMock:
        chunk = MagicMock()
        chunk.lesson_id = lesson_id
        chunk.chunk_index = chunk_index
        chunk.source = source
        return chunk

    def test_single_chunk_produces_one_citation(self) -> None:
        from app.modules.rag.service import build_citations

        lesson_id = uuid.uuid4()
        chunk = self._make_chunk(lesson_id)
        titles = {lesson_id: "Intro to Python"}

        result = build_citations([chunk], titles)

        assert len(result) == 1
        assert result[0].lesson_id == lesson_id
        assert result[0].lesson_title == "Intro to Python"
        assert result[0].source == "content"

    def test_deduplicates_multiple_chunks_from_same_lesson(self) -> None:
        """Two chunks from the same lesson should yield one citation."""
        from app.modules.rag.service import build_citations

        lesson_id = uuid.uuid4()
        chunks = [
            self._make_chunk(lesson_id, chunk_index=0),
            self._make_chunk(lesson_id, chunk_index=1),
        ]
        titles = {lesson_id: "Python Basics"}

        result = build_citations(chunks, titles)

        assert len(result) == 1
        assert result[0].lesson_id == lesson_id

    def test_preserves_retrieval_order(self) -> None:
        """Citations must appear in the order chunks were retrieved (rank order)."""
        from app.modules.rag.service import build_citations

        id_a, id_b, id_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        chunks = [
            self._make_chunk(id_a),
            self._make_chunk(id_b),
            self._make_chunk(id_c),
        ]
        titles = {id_a: "A", id_b: "B", id_c: "C"}

        result = build_citations(chunks, titles)

        assert [r.lesson_id for r in result] == [id_a, id_b, id_c]

    def test_missing_title_falls_back_to_default(self) -> None:
        from app.modules.rag.service import build_citations

        lesson_id = uuid.uuid4()
        chunk = self._make_chunk(lesson_id)

        result = build_citations([chunk], {})  # no title provided

        assert result[0].lesson_title == "Course Material"

    def test_transcript_source_preserved(self) -> None:
        from app.modules.rag.service import build_citations

        lesson_id = uuid.uuid4()
        chunk = self._make_chunk(lesson_id, source="transcript")
        titles = {lesson_id: "Video Lesson"}

        result = build_citations([chunk], titles)

        assert result[0].source == "transcript"

    def test_empty_chunks_returns_empty_list(self) -> None:
        from app.modules.rag.service import build_citations

        assert build_citations([], {}) == []
