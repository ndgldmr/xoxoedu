"""Integration tests for Sprint 8A — video upload, Mux webhook, and transcripts."""

import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.course import Chapter, Course, Lesson, LessonTranscript
from app.db.models.user import User, UserProfile


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession, email: str, role: str = "admin"
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass123"),
        role=role,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name=email.split("@")[0]))
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_video_lesson(db: AsyncSession, created_by: uuid.UUID) -> Lesson:
    course = Course(
        slug=f"video-course-{uuid.uuid4().hex[:8]}",
        title="Video Course",
        level="beginner",
        language="en",
        price_cents=0,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.flush()

    chapter = Chapter(
        course_id=course.id,
        title="Chapter 1",
        position=1,
    )
    db.add(chapter)
    await db.flush()

    lesson = Lesson(
        chapter_id=chapter.id,
        title="Video Lesson",
        type="video",
        position=1,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


def _mux_signature(body: bytes, secret: str) -> str:
    """Build a valid mux-signature header for testing."""
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.".encode() + body
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


# ── Video upload endpoint ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_video_upload_returns_upload_url(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Admin POST /admin/lessons/{id}/video returns a Mux upload URL."""
    admin, token = await _make_user(db, "admin-upload@example.com")
    lesson = await _make_video_lesson(db, admin.id)

    with patch("app.modules.admin.router.create_upload") as mock_upload:
        mock_upload.return_value = ("https://storage.googleapis.com/mux-uploads/fake", "asset-abc")

        resp = await client.post(
            f"/api/v1/admin/lessons/{lesson.id}/video",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["upload_url"].startswith("https://")
    assert data["asset_id"] == "asset-abc"


@pytest.mark.asyncio
async def test_request_video_upload_persists_asset_id(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Asset ID is saved on the lesson row after requesting an upload."""
    admin, token = await _make_user(db, "admin-persist@example.com")
    lesson = await _make_video_lesson(db, admin.id)

    with patch("app.modules.admin.router.create_upload") as mock_upload:
        mock_upload.return_value = ("https://mux.com/upload/url", "asset-xyz")
        await client.post(
            f"/api/v1/admin/lessons/{lesson.id}/video",
            headers={"Authorization": f"Bearer {token}"},
        )

    await db.refresh(lesson)
    assert lesson.video_asset_id == "asset-xyz"


@pytest.mark.asyncio
async def test_request_video_upload_lesson_not_found(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin-notfound@example.com")
    resp = await client.post(
        f"/api/v1/admin/lessons/{uuid.uuid4()}/video",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── Mux webhook ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mux_webhook_asset_ready_enqueues_task(
    client: AsyncClient, db: AsyncSession
) -> None:
    """video.asset.ready event saves playback_id and enqueues transcript task."""
    admin, _ = await _make_user(db, "admin-webhook@example.com")
    lesson = await _make_video_lesson(db, admin.id)
    lesson.video_asset_id = "asset-ready-123"
    await db.commit()

    payload = json.dumps({
        "type": "video.asset.ready",
        "data": {
            "id": "asset-ready-123",
            "playback_ids": [{"id": "playback-abc", "policy": "signed"}],
        },
    }).encode()

    secret = "testsecret"
    sig_header = _mux_signature(payload, secret)

    with (
        patch("app.modules.video.router.settings.MUX_WEBHOOK_SECRET", secret),
        patch("app.modules.video.tasks.generate_transcript.delay") as mock_delay,
    ):
        resp = await client.post(
            "/api/v1/webhooks/mux",
            content=payload,
            headers={"content-type": "application/json", "mux-signature": sig_header},
        )

    assert resp.status_code == 200
    assert resp.json() == {"received": True}

    await db.refresh(lesson)
    assert lesson.mux_playback_id == "playback-abc"
    mock_delay.assert_called_once_with(str(lesson.id))


@pytest.mark.asyncio
async def test_mux_webhook_upload_asset_created_swaps_asset_id(
    client: AsyncClient, db: AsyncSession
) -> None:
    """video.upload.asset_created swaps upload_id → real asset_id on the lesson."""
    admin, _ = await _make_user(db, "admin-upload-created@example.com")
    lesson = await _make_video_lesson(db, admin.id)
    lesson.video_asset_id = "upload-id-123"
    await db.commit()

    payload = json.dumps({
        "type": "video.upload.asset_created",
        "data": {
            "id": "upload-id-123",
            "asset_id": "real-asset-id-456",
        },
    }).encode()

    secret = "testsecret"
    sig_header = _mux_signature(payload, secret)

    with patch("app.modules.video.router.settings.MUX_WEBHOOK_SECRET", secret):
        resp = await client.post(
            "/api/v1/webhooks/mux",
            content=payload,
            headers={"content-type": "application/json", "mux-signature": sig_header},
        )

    assert resp.status_code == 200
    await db.refresh(lesson)
    assert lesson.video_asset_id == "real-asset-id-456"


@pytest.mark.asyncio
async def test_mux_webhook_bad_signature_rejected(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Webhook with invalid signature returns 400."""
    payload = b'{"type":"video.asset.ready","data":{"id":"x","playback_ids":[]}}'
    with patch("app.modules.video.router.settings.MUX_WEBHOOK_SECRET", "secret"):
        resp = await client.post(
            "/api/v1/webhooks/mux",
            content=payload,
            headers={"content-type": "application/json", "mux-signature": "t=1,v1=badsig"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mux_webhook_unknown_event_ignored(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Unknown event types are accepted but produce no side effects."""
    payload = json.dumps({"type": "video.asset.created", "data": {}}).encode()
    secret = "testsecret"
    sig_header = _mux_signature(payload, secret)

    with patch("app.modules.video.router.settings.MUX_WEBHOOK_SECRET", secret):
        resp = await client.post(
            "/api/v1/webhooks/mux",
            content=payload,
            headers={"content-type": "application/json", "mux-signature": sig_header},
        )
    assert resp.status_code == 200


# ── Transcript endpoints ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_transcript_returns_vtt_url_and_plain_text(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /lessons/{id}/transcript returns vtt_url and plain_text."""
    admin, token = await _make_user(db, "admin-transcript-get@example.com")
    lesson = await _make_video_lesson(db, admin.id)

    transcript = LessonTranscript(
        lesson_id=lesson.id,
        vtt_key=f"transcripts/{lesson.id}/transcript.vtt",
        plain_text="Hello world this is a transcript.",
    )
    db.add(transcript)
    await db.commit()

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/transcript",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "vtt_url" in data
    assert data["plain_text"] == "Hello world this is a transcript."


@pytest.mark.asyncio
async def test_get_transcript_not_found(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin, token = await _make_user(db, "admin-transcript-404@example.com")
    resp = await client.get(
        f"/api/v1/lessons/{uuid.uuid4()}/transcript",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_edit_transcript(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH /lessons/{id}/transcript updates plain_text and re-uploads VTT."""
    admin, token = await _make_user(db, "admin-transcript-patch@example.com")
    lesson = await _make_video_lesson(db, admin.id)

    transcript = LessonTranscript(
        lesson_id=lesson.id,
        vtt_key=f"transcripts/{lesson.id}/transcript.vtt",
        plain_text="Original text.",
    )
    db.add(transcript)
    await db.commit()

    mock_r2 = MagicMock()
    with patch("app.modules.video.router.get_r2_client", return_value=mock_r2):
        resp = await client.patch(
            f"/api/v1/lessons/{lesson.id}/transcript",
            json={"plain_text": "Corrected transcript text."},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plain_text"] == "Corrected transcript text."

    # R2 put_object should have been called to re-upload the VTT
    mock_r2.put_object.assert_called_once()


@pytest.mark.asyncio
async def test_generate_transcript_task_stores_transcript(
    db: AsyncSession,
) -> None:
    """generate_transcript task writes a LessonTranscript row (mocked Whisper + R2)."""
    from app.modules.video.tasks import generate_transcript

    admin, _ = await _make_user(db, "admin-task@example.com")
    lesson = await _make_video_lesson(db, admin.id)
    lesson.video_asset_id = "asset-task-test"
    lesson.mux_playback_id = "playback-task-test"
    await db.commit()

    whisper_segment = MagicMock()
    whisper_segment.model_dump.return_value = {
        "start": 0.0,
        "end": 3.0,
        "text": " Task transcript text.",
    }
    whisper_response = MagicMock()
    whisper_response.segments = [whisper_segment]

    mock_r2 = MagicMock()

    with (
        patch("app.modules.video.tasks.subprocess.run"),  # skip actual ffmpeg
        patch("app.modules.video.tasks.openai.OpenAI") as mock_openai_cls,
        patch("app.modules.video.tasks.get_r2_client", return_value=mock_r2),
    ):
        mock_openai_cls.return_value.audio.transcriptions.create.return_value = whisper_response

        generate_transcript.apply(args=[str(lesson.id)])

    await db.expire_all()
    row = (await db.execute(
        select(LessonTranscript).where(LessonTranscript.lesson_id == lesson.id)
    )).scalar_one_or_none()

    assert row is not None
    assert "Task transcript text." in row.plain_text
    mock_r2.put_object.assert_called_once()
