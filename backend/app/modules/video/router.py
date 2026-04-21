"""FastAPI router for Mux webhook reception and lesson transcript endpoints."""

from __future__ import annotations

import hashlib
import hmac
import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import InvalidWebhookSignature, LessonNotFound
from app.core.rbac import Role, require_role
from app.core.responses import ok
from app.core.storage import get_public_url
from app.db.models.course import Lesson, LessonTranscript
from app.db.session import get_db
from app.modules.video.schemas import TranscriptOut, TranscriptUpdateIn

router = APIRouter(tags=["video"])


# ── Mux webhook ────────────────────────────────────────────────────────────────

@router.post("/webhooks/mux", include_in_schema=False)
async def mux_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    mux_signature: str = Header(alias="mux-signature", default=""),
) -> dict:
    """Receive and process Mux webhook events.

    Verifies the HMAC-SHA256 signature supplied in the ``mux-signature`` header
    before processing.  On a ``video.asset.ready`` event, saves the playback ID
    to the lesson and enqueues the transcription task.

    Args:
        request: Raw FastAPI request (body read as bytes for signature check).
        db: Async database session.
        mux_signature: Value of the ``mux-signature`` header sent by Mux.

    Returns:
        ``{"received": True}`` on success.

    Raises:
        InvalidWebhookSignature: If the HMAC check fails.
    """
    body = await request.body()
    _verify_mux_signature(body, mux_signature)

    payload = await request.json()
    event_type: str = payload.get("type", "")
    data: dict = payload.get("data", {})

    if event_type == "video.upload.asset_created":
        # Mux fires this when the client finishes uploading.
        # data.id = upload ID (what we stored on the lesson)
        # data.asset_id = the real Mux asset ID — swap it in now.
        upload_id: str = data.get("id", "")
        asset_id: str = data.get("asset_id", "")

        if upload_id and asset_id:
            result = await db.execute(
                select(Lesson).where(Lesson.video_asset_id == upload_id)
            )
            lesson = result.scalar_one_or_none()
            if lesson is not None:
                lesson.video_asset_id = asset_id
                await db.commit()

    elif event_type == "video.asset.ready":
        # Mux fires this when transcoding is complete.
        # data.id = asset ID; data.playback_ids = usable playback IDs.
        asset_id = data.get("id", "")
        playback_ids: list[dict] = data.get("playback_ids", [])
        playback_id: str = playback_ids[0]["id"] if playback_ids else ""

        result = await db.execute(
            select(Lesson).where(Lesson.video_asset_id == asset_id)
        )
        lesson = result.scalar_one_or_none()

        if lesson is not None and playback_id:
            lesson.mux_playback_id = playback_id
            await db.commit()

            from app.modules.video.tasks import generate_transcript
            generate_transcript.delay(str(lesson.id))

    return {"received": True}


def _verify_mux_signature(body: bytes, mux_signature_header: str) -> None:
    """Verify the Mux webhook HMAC-SHA256 signature.

    Mux sends a ``mux-signature`` header in the form ``t=<timestamp>,v1=<hex>``.
    The signed payload is ``<timestamp>.<body>``.

    Args:
        body: Raw request body bytes.
        mux_signature_header: Value of the ``mux-signature`` header.

    Raises:
        InvalidWebhookSignature: If the signature is missing, malformed, or invalid.
    """
    if not settings.MUX_WEBHOOK_SECRET or not mux_signature_header:
        raise InvalidWebhookSignature()

    parts = dict(part.split("=", 1) for part in mux_signature_header.split(",") if "=" in part)
    timestamp = parts.get("t", "")
    signature = parts.get("v1", "")

    if not timestamp or not signature:
        raise InvalidWebhookSignature()

    signed_payload = f"{timestamp}.".encode() + body
    expected = hmac.new(
        settings.MUX_WEBHOOK_SECRET.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise InvalidWebhookSignature()


# ── Transcript endpoints ───────────────────────────────────────────────────────

@router.get("/lessons/{lesson_id}/transcript")
async def get_transcript(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the transcript for a video lesson.

    Args:
        lesson_id: UUID of the lesson.
        db: Async database session.

    Returns:
        ``TranscriptOut`` with the VTT public URL and plain text.

    Raises:
        LessonNotFound: When no transcript exists for the lesson.
    """
    result = await db.execute(
        select(LessonTranscript).where(LessonTranscript.lesson_id == lesson_id)
    )
    transcript = result.scalar_one_or_none()
    if transcript is None:
        raise LessonNotFound()

    return ok(
        TranscriptOut(
            lesson_id=lesson_id,
            vtt_url=get_public_url(transcript.vtt_key),
            plain_text=transcript.plain_text,
            updated_at=transcript.updated_at,
        ).model_dump()
    )


@router.patch(
    "/lessons/{lesson_id}/transcript",
    dependencies=[require_role(Role.ADMIN)],
)
async def update_transcript(
    lesson_id: uuid.UUID,
    body: TranscriptUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin endpoint to edit the plain-text transcript for a lesson.

    Regenerates and re-uploads the VTT file from the edited plain text.
    The updated ``plain_text`` is also what Sprint 8B will index for RAG.

    Args:
        lesson_id: UUID of the lesson whose transcript is being edited.
        body: ``TranscriptUpdateIn`` containing the new plain text.
        db: Async database session.

    Returns:
        Updated ``TranscriptOut``.

    Raises:
        LessonNotFound: When no transcript exists for the lesson.
    """
    import io
    from datetime import UTC, datetime

    from app.core.storage import get_r2_client

    result = await db.execute(
        select(LessonTranscript).where(LessonTranscript.lesson_id == lesson_id)
    )
    transcript = result.scalar_one_or_none()
    if transcript is None:
        raise LessonNotFound()

    # Rebuild a simple VTT with no timestamps — plain text edit loses segment timing
    vtt_content = f"WEBVTT\n\n1\n00:00:00.000 --> 99:59:59.999\n{body.plain_text}\n"
    r2 = get_r2_client()
    r2.put_object(
        Bucket=settings.R2_BUCKET,
        Key=transcript.vtt_key,
        Body=io.BytesIO(vtt_content.encode()),
        ContentType="text/vtt",
    )

    transcript.plain_text = body.plain_text
    transcript.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(transcript)

    from app.modules.rag.tasks import index_lesson
    index_lesson.delay(str(lesson_id))

    return ok(
        TranscriptOut(
            lesson_id=lesson_id,
            vtt_url=get_public_url(transcript.vtt_key),
            plain_text=transcript.plain_text,
            updated_at=transcript.updated_at,
        ).model_dump()
    )
