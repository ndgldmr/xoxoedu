"""Integration tests for the RAG course assistant — Sprint 9A & 9B."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.assistant import Conversation, ConversationMessage
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment
from app.db.models.rag import LessonChunk
from app.db.models.user import User
from app.modules.ai.client import LLMResponse


# ── Fixture helpers ────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession, email: str, role: str = "student"
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass"),
        role=role,
        email_verified=True,
        display_name=email.split("@")[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_course(db: AsyncSession, created_by: uuid.UUID) -> Course:
    course = Course(
        slug=f"rag-course-{uuid.uuid4().hex[:8]}",
        title="RAG Test Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _make_lesson(db: AsyncSession, course: Course) -> Lesson:
    chapter = Chapter(course_id=course.id, title="Chapter 1", position=1)
    db.add(chapter)
    await db.flush()
    lesson = Lesson(
        chapter_id=chapter.id,
        title="Intro to Python",
        position=1,
        type="text",
        is_free_preview=False,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


async def _make_enrollment(
    db: AsyncSession, user: User, course: Course
) -> Enrollment:
    enrollment = Enrollment(
        user_id=user.id,
        course_id=course.id,
        status="active",
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def _make_chunk(
    db: AsyncSession, lesson: Lesson, course: Course, body: str = "Python is a language."
) -> LessonChunk:
    chunk = LessonChunk(
        lesson_id=lesson.id,
        course_id=course.id,
        chunk_index=0,
        source="content",
        body=body,
        embedding=[0.1] * 1536,
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return chunk


# ── Shared mocks ───────────────────────────────────────────────────────────────

def _mock_embedding(embedding: list[float] | None = None) -> AsyncMock:
    """Return a mock for openai.AsyncOpenAI that yields a deterministic embedding."""
    vec = embedding or ([0.1] * 1536)
    embed_item = MagicMock()
    embed_item.embedding = vec
    embed_response = MagicMock()
    embed_response.data = [embed_item]

    client_instance = AsyncMock()
    client_instance.embeddings.create = AsyncMock(return_value=embed_response)
    return client_instance


def _mock_llm(content: str = "Here is the answer.") -> LLMResponse:
    return LLMResponse(
        content=content,
        tokens_in=50,
        tokens_out=20,
        model="gemini/gemini-2.0-flash",
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestAskAssistant:
    """POST /api/v1/courses/{course_id}/assistant"""

    @pytest.mark.asyncio
    async def test_full_pipeline_returns_answer(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Happy path: enrolled student gets an LLM-generated answer."""
        admin, _ = await _make_user(db, "rag-admin@test.com", "admin")
        student, token = await _make_user(db, "rag-student@test.com")
        course = await _make_course(db, admin.id)
        lesson = await _make_lesson(db, course)
        await _make_enrollment(db, student, course)
        await _make_chunk(db, lesson, course, body="Python is a high-level programming language.")

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.complete") as mock_llm,
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            mock_llm.return_value = _mock_llm("Python is a high-level language.")

            resp = await client.post(
                f"/api/v1/courses/{course.id}/assistant",
                json={"question": "What is Python?"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["message"]["content"] == "Python is a high-level language."
        assert data["message"]["role"] == "assistant"
        assert "conversation_id" in data
        assert isinstance(data["retrieved_lesson_ids"], list)

    @pytest.mark.asyncio
    async def test_creates_conversation_on_first_call(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """First call should create a Conversation row in the DB."""
        admin, _ = await _make_user(db, "rag-conv-admin@test.com", "admin")
        student, token = await _make_user(db, "rag-conv-student@test.com")
        course = await _make_course(db, admin.id)
        await _make_lesson(db, course)
        await _make_enrollment(db, student, course)

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.complete") as mock_llm,
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            mock_llm.return_value = _mock_llm()

            resp = await client.post(
                f"/api/v1/courses/{course.id}/assistant",
                json={"question": "Hello?"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        conv_id = uuid.UUID(resp.json()["data"]["conversation_id"])

        from sqlalchemy import select
        conv = await db.scalar(select(Conversation).where(Conversation.id == conv_id))
        assert conv is not None
        assert conv.user_id == student.id
        assert conv.course_id == course.id

    @pytest.mark.asyncio
    async def test_continues_existing_conversation(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Second call reuses the same conversation_id, doesn't create a new one."""
        admin, _ = await _make_user(db, "rag-cont-admin@test.com", "admin")
        student, token = await _make_user(db, "rag-cont-student@test.com")
        course = await _make_course(db, admin.id)
        await _make_lesson(db, course)
        await _make_enrollment(db, student, course)

        kwargs = dict(
            json={"question": "Any question"},
            headers={"Authorization": f"Bearer {token}"},
        )

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.complete") as mock_llm,
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            mock_llm.return_value = _mock_llm()

            r1 = await client.post(f"/api/v1/courses/{course.id}/assistant", **kwargs)
            r2 = await client.post(f"/api/v1/courses/{course.id}/assistant", **kwargs)

        assert r1.json()["data"]["conversation_id"] == r2.json()["data"]["conversation_id"]

    @pytest.mark.asyncio
    async def test_not_enrolled_returns_403(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Student with no enrollment must receive 403."""
        admin, _ = await _make_user(db, "rag-403-admin@test.com", "admin")
        student, token = await _make_user(db, "rag-403-student@test.com")
        course = await _make_course(db, admin.id)

        resp = await client.post(
            f"/api/v1/courses/{course.id}/assistant",
            json={"question": "Any question"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "NOT_ENROLLED"

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_400(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        resp = await client.post(
            f"/api/v1/courses/{uuid.uuid4()}/assistant",
            json={"question": "Hello"},
        )
        assert resp.status_code in (400, 401, 403)

    @pytest.mark.asyncio
    async def test_persists_both_turns(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Both the user question and assistant reply must be saved as messages."""
        admin, _ = await _make_user(db, "rag-turns-admin@test.com", "admin")
        student, token = await _make_user(db, "rag-turns-student@test.com")
        course = await _make_course(db, admin.id)
        lesson = await _make_lesson(db, course)
        await _make_enrollment(db, student, course)
        await _make_chunk(db, lesson, course)

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.complete") as mock_llm,
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            mock_llm.return_value = _mock_llm("Great answer.")

            resp = await client.post(
                f"/api/v1/courses/{course.id}/assistant",
                json={"question": "Explain Python."},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        conv_id = uuid.UUID(resp.json()["data"]["conversation_id"])

        from sqlalchemy import select
        msgs = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conv_id)
                .order_by(ConversationMessage.created_at)
            )
        )
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "Explain Python."
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "Great answer."


class TestScopeEnforcement:
    """Students of course A cannot receive chunks from course B."""

    @pytest.mark.asyncio
    async def test_cross_course_chunk_isolation(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Chunks from course B must never appear in a course A response."""
        admin, _ = await _make_user(db, "scope-admin@test.com", "admin")
        student, token = await _make_user(db, "scope-student@test.com")

        course_a = await _make_course(db, admin.id)
        course_b = await _make_course(db, admin.id)

        lesson_a = await _make_lesson(db, course_a)
        lesson_b = await _make_lesson(db, course_b)

        # Enroll only in course A
        await _make_enrollment(db, student, course_a)

        # Index a chunk in course B with an identical embedding so it would
        # rank first without the scope filter
        await _make_chunk(db, lesson_a, course_a, body="Course A content.")
        await _make_chunk(db, lesson_b, course_b, body="Course B secret content.")

        captured_ids: list[str] = []

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.complete") as mock_llm,
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            mock_llm.return_value = _mock_llm("Answer from course A.")

            resp = await client.post(
                f"/api/v1/courses/{course_a.id}/assistant",
                json={"question": "Tell me about course content."},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        retrieved = resp.json()["data"]["retrieved_lesson_ids"]
        # lesson_b (from course B) must NOT appear in retrieved IDs
        assert str(lesson_b.id) not in retrieved


class TestRateLimiting:
    """POST /assistant is rate-limited to 20 queries per student per hour per course."""

    @pytest.mark.asyncio
    async def test_rate_limit_enforced_after_20_requests(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        from app.modules.rag.service import _RATE_LIMIT_MAX

        admin, _ = await _make_user(db, "rl-admin@test.com", "admin")
        student, token = await _make_user(db, "rl-student@test.com")
        course = await _make_course(db, admin.id)
        lesson = await _make_lesson(db, course)
        await _make_enrollment(db, student, course)
        await _make_chunk(db, lesson, course)

        call_count = 0

        async def fake_incr(key: str) -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        async def fake_expire(key: str, secs: int) -> None:
            pass

        mock_redis = AsyncMock()
        mock_redis.incr = fake_incr
        mock_redis.expire = fake_expire

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.complete") as mock_llm,
            patch("app.modules.rag.service.log_ai_usage.delay"),
            patch("app.modules.rag.service.get_redis", return_value=mock_redis),
        ):
            mock_oai.return_value = _mock_embedding()
            mock_llm.return_value = _mock_llm()

            last_ok = None
            for i in range(_RATE_LIMIT_MAX):
                r = await client.post(
                    f"/api/v1/courses/{course.id}/assistant",
                    json={"question": f"Question {i}"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                last_ok = r

            # 21st request must be rejected
            over = await client.post(
                f"/api/v1/courses/{course.id}/assistant",
                json={"question": "One too many"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert last_ok is not None and last_ok.status_code == 200
        assert over.status_code == 429
        assert over.json()["error"]["code"] == "ASSISTANT_RATE_LIMITED"


class TestListConversations:
    """GET /api/v1/assistant/conversations"""

    @pytest.mark.asyncio
    async def test_returns_student_conversations(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        admin, _ = await _make_user(db, "list-admin@test.com", "admin")
        student, token = await _make_user(db, "list-student@test.com")
        course = await _make_course(db, admin.id)
        await _make_lesson(db, course)
        await _make_enrollment(db, student, course)

        # Create a conversation directly
        conv = Conversation(user_id=student.id, course_id=course.id)
        db.add(conv)
        await db.commit()

        resp = await client.get(
            "/api/v1/assistant/conversations",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert isinstance(data, list)
        assert any(str(d["course_id"]) == str(course.id) for d in data)

    @pytest.mark.asyncio
    async def test_filter_by_course_id(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        admin, _ = await _make_user(db, "filter-admin@test.com", "admin")
        student, token = await _make_user(db, "filter-student@test.com")
        course_a = await _make_course(db, admin.id)
        course_b = await _make_course(db, admin.id)
        await _make_lesson(db, course_a)
        await _make_lesson(db, course_b)

        for course in (course_a, course_b):
            conv = Conversation(user_id=student.id, course_id=course.id)
            db.add(conv)
        await db.commit()

        resp = await client.get(
            f"/api/v1/assistant/conversations?course_id={course_a.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert all(str(d["course_id"]) == str(course_a.id) for d in data)

    @pytest.mark.asyncio
    async def test_does_not_return_other_students_conversations(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        admin, _ = await _make_user(db, "iso-admin@test.com", "admin")
        student_a, token_a = await _make_user(db, "iso-student-a@test.com")
        student_b, _ = await _make_user(db, "iso-student-b@test.com")
        course = await _make_course(db, admin.id)

        conv_b = Conversation(user_id=student_b.id, course_id=course.id)
        db.add(conv_b)
        await db.commit()

        resp = await client.get(
            "/api/v1/assistant/conversations",
            headers={"Authorization": f"Bearer {token_a}"},
        )

        assert resp.status_code == 200
        conv_ids = [d["id"] for d in resp.json()["data"]]
        assert str(conv_b.id) not in conv_ids


# ── SSE helpers ────────────────────────────────────────────────────────────────

def _parse_sse(body: str) -> list[dict]:
    """Parse a raw SSE response body into a list of event dicts.

    Each dict has ``event`` (default ``"message"``) and ``data`` keys.
    """
    events: list[dict] = []
    current: dict = {}
    for line in body.splitlines():
        if line.startswith("event:"):
            current["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:"):].strip()
        elif line == "" and current:
            current.setdefault("event", "message")
            events.append(current)
            current = {}
    if current:
        current.setdefault("event", "message")
        events.append(current)
    return events


async def _make_conversation(
    db: AsyncSession, user: "User", course: "Course"
) -> "Conversation":
    conv = Conversation(user_id=user.id, course_id=course.id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


# ── Sprint 9B: streaming tests ─────────────────────────────────────────────────

class TestStreamAssistant:
    """GET /api/v1/assistant/conversations/{id}/stream"""

    @pytest.mark.asyncio
    async def test_stream_returns_token_events(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Each LLM delta must arrive as a data event with a 'token' key."""
        admin, _ = await _make_user(db, "stream-admin@test.com", "admin")
        student, token = await _make_user(db, "stream-student@test.com")
        course = await _make_course(db, admin.id)
        lesson = await _make_lesson(db, course)
        await _make_enrollment(db, student, course)
        await _make_chunk(db, lesson, course)
        conv = await _make_conversation(db, student, course)

        async def fake_stream(messages, *, temperature=0.3):
            for word in ["Python", " is", " great"]:
                yield word

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.stream", side_effect=fake_stream),
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            resp = await client.get(
                f"/api/v1/assistant/conversations/{conv.id}/stream",
                params={"question": "What is Python?"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        token_events = [e for e in events if e["event"] == "message"]
        import json
        tokens = [json.loads(e["data"])["token"] for e in token_events]
        assert tokens == ["Python", " is", " great"]

    @pytest.mark.asyncio
    async def test_stream_full_response_matches_assembled_text(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Concatenating all token events must reproduce the full assistant reply."""
        admin, _ = await _make_user(db, "stream-full-admin@test.com", "admin")
        student, token = await _make_user(db, "stream-full-student@test.com")
        course = await _make_course(db, admin.id)
        lesson = await _make_lesson(db, course)
        await _make_enrollment(db, student, course)
        await _make_chunk(db, lesson, course)
        conv = await _make_conversation(db, student, course)

        words = ["Hello", " world", "!"]

        async def fake_stream(messages, *, temperature=0.3):
            for w in words:
                yield w

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.stream", side_effect=fake_stream),
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            resp = await client.get(
                f"/api/v1/assistant/conversations/{conv.id}/stream",
                params={"question": "Say hello."},
                headers={"Authorization": f"Bearer {token}"},
            )

        import json
        events = _parse_sse(resp.text)
        token_events = [e for e in events if e["event"] == "message"]
        assembled = "".join(json.loads(e["data"])["token"] for e in token_events)
        assert assembled == "Hello world!"

    @pytest.mark.asyncio
    async def test_stream_emits_citations_event(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """A 'citations' event must be present and reference the retrieved lesson."""
        admin, _ = await _make_user(db, "stream-cite-admin@test.com", "admin")
        student, token = await _make_user(db, "stream-cite-student@test.com")
        course = await _make_course(db, admin.id)
        lesson = await _make_lesson(db, course)
        await _make_enrollment(db, student, course)
        await _make_chunk(db, lesson, course, body="Python basics.")
        conv = await _make_conversation(db, student, course)

        async def fake_stream(messages, *, temperature=0.3):
            yield "Answer."

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.stream", side_effect=fake_stream),
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            resp = await client.get(
                f"/api/v1/assistant/conversations/{conv.id}/stream",
                params={"question": "What is Python?"},
                headers={"Authorization": f"Bearer {token}"},
            )

        import json
        events = _parse_sse(resp.text)
        citation_events = [e for e in events if e["event"] == "citations"]
        assert len(citation_events) == 1
        payload = json.loads(citation_events[0]["data"])
        assert "citations" in payload
        assert any(str(lesson.id) == c["lesson_id"] for c in payload["citations"])

    @pytest.mark.asyncio
    async def test_stream_emits_done_event(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The final event must be 'done'."""
        admin, _ = await _make_user(db, "stream-done-admin@test.com", "admin")
        student, token = await _make_user(db, "stream-done-student@test.com")
        course = await _make_course(db, admin.id)
        lesson = await _make_lesson(db, course)
        await _make_enrollment(db, student, course)
        await _make_chunk(db, lesson, course)
        conv = await _make_conversation(db, student, course)

        async def fake_stream(messages, *, temperature=0.3):
            yield "Done."

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.stream", side_effect=fake_stream),
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            resp = await client.get(
                f"/api/v1/assistant/conversations/{conv.id}/stream",
                params={"question": "Any?"},
                headers={"Authorization": f"Bearer {token}"},
            )

        events = _parse_sse(resp.text)
        assert events[-1]["event"] == "done"

    @pytest.mark.asyncio
    async def test_stream_persists_both_turns(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Both user question and assembled assistant reply must be saved."""
        from sqlalchemy import select as sa_select
        admin, _ = await _make_user(db, "stream-persist-admin@test.com", "admin")
        student, token = await _make_user(db, "stream-persist-student@test.com")
        course = await _make_course(db, admin.id)
        lesson = await _make_lesson(db, course)
        await _make_enrollment(db, student, course)
        await _make_chunk(db, lesson, course)
        conv = await _make_conversation(db, student, course)

        async def fake_stream(messages, *, temperature=0.3):
            for w in ["Hello", " there"]:
                yield w

        with (
            patch("app.modules.rag.service.openai.AsyncOpenAI") as mock_oai,
            patch("app.modules.rag.service.llm_client.stream", side_effect=fake_stream),
            patch("app.modules.rag.service.log_ai_usage.delay"),
        ):
            mock_oai.return_value = _mock_embedding()
            await client.get(
                f"/api/v1/assistant/conversations/{conv.id}/stream",
                params={"question": "Greet me."},
                headers={"Authorization": f"Bearer {token}"},
            )

        msgs = list(await db.scalars(
            sa_select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.created_at)
        ))
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "Greet me."
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "Hello there"

    @pytest.mark.asyncio
    async def test_stream_not_enrolled_returns_403(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        admin, _ = await _make_user(db, "stream-403-admin@test.com", "admin")
        student, token = await _make_user(db, "stream-403-student@test.com")
        other, _ = await _make_user(db, "stream-403-other@test.com")
        course = await _make_course(db, admin.id)
        await _make_lesson(db, course)
        # other is enrolled but student is not
        await _make_enrollment(db, other, course)
        conv = await _make_conversation(db, other, course)

        resp = await client.get(
            f"/api/v1/assistant/conversations/{conv.id}/stream",
            params={"question": "Hello?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # conversation doesn't belong to this student → 404
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_stream_unknown_conversation_returns_404(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        _, token = await _make_user(db, "stream-404-student@test.com")

        resp = await client.get(
            f"/api/v1/assistant/conversations/{uuid.uuid4()}/stream",
            params={"question": "Hello?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
