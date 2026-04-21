"""Celery task for async video transcription via OpenAI Whisper."""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.retry import media_backoff


def _seconds_to_vtt_timestamp(seconds: float) -> str:
    """Convert a float second offset to WebVTT timestamp format ``HH:MM:SS.mmm``.

    Args:
        seconds: Time offset in seconds.

    Returns:
        A WebVTT-formatted timestamp string.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def _build_vtt(segments: list[dict]) -> str:
    """Convert Whisper verbose_json segments to a WebVTT string.

    Args:
        segments: The ``segments`` list from a Whisper ``verbose_json`` response.
            Each segment has ``start``, ``end``, and ``text`` keys.

    Returns:
        A complete WebVTT file as a string, ready to upload.
    """
    lines = ["WEBVTT", ""]
    for i, seg in enumerate(segments, start=1):
        start = _seconds_to_vtt_timestamp(seg["start"])
        end = _seconds_to_vtt_timestamp(seg["end"])
        text = seg["text"].strip()
        lines += [str(i), f"{start} --> {end}", text, ""]
    return "\n".join(lines)


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=3,
    soft_time_limit=580,
    time_limit=700,
)
def generate_transcript(self, lesson_id: str) -> None:
    """Download audio from Mux, transcribe via Whisper, and store the result.

    Steps:
    1. Load the lesson and resolve its Mux asset ID.
    2. Download the audio-only rendition from Mux into a temporary file.
    3. Send the audio to OpenAI Whisper (``verbose_json`` for timestamps).
    4. Convert the Whisper segments to WebVTT format.
    5. Upload the VTT file to R2.
    6. Upsert a ``lesson_transcripts`` row with ``vtt_key`` and ``plain_text``.

    Idempotency: if a transcript row already exists for the lesson, the task
    overwrites it — a re-trigger (e.g. after an admin manually re-runs
    transcription) should always produce a fresh result.

    Task status is recorded in Redis under
    ``task:status:generate_transcript:{lesson_id}`` **only after the initial
    guard checks pass** (lesson exists and has a Mux playback ID), so early
    returns leave no stale "started" record.  The ``retry_stuck_transcriptions``
    beat task uses this key to avoid re-enqueueing a lesson whose transcription
    is actively running.

    Retries up to 3 times with exponential backoff (60 s → 120 s → 600 s).
    The soft time limit (580 s) fires 20 seconds before the hard kill (700 s)
    so that cleanup has time to complete.  The ffmpeg subprocess timeout (540 s)
    is set below the soft limit to ensure it terminates cleanly before the
    signal fires.

    Args:
        lesson_id: String UUID of the ``Lesson`` to transcribe.
    """
    # rdb is initialised inside the try block after guard checks; held here so
    # the except handler can reference it without a NameError.
    rdb = None
    task_id = str(self.request.id)

    try:
        import io
        import subprocess
        import tempfile
        import uuid as _uuid

        import openai
        import redis as sync_redis
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.core.mux import get_hls_url
        from app.core.storage import get_r2_client
        from app.db.models.course import Lesson, LessonTranscript
        from app.worker.task_status import record_failure, record_started, record_success

        lesson_uuid = _uuid.UUID(lesson_id)
        engine = create_engine(settings.DATABASE_URL_SYNC)

        with Session(engine) as db:
            lesson = db.execute(
                select(Lesson).where(Lesson.id == lesson_uuid)
            ).scalar_one_or_none()

            if lesson is None or not lesson.mux_playback_id:
                # No-op: leave no status record so the beat task can still
                # re-enqueue if the condition changes (e.g. mux_playback_id set later).
                return

            # Guard checks passed — record that actual transcription work begins.
            rdb = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
            record_started(rdb, "generate_transcript", lesson_id, task_id)

            hls_url = get_hls_url(lesson.mux_playback_id)

            # Use ffmpeg to extract audio from the HLS stream into a temp file.
            # This works on all Mux plans — no static MP4 rendition required.
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", hls_url,
                        "-vn",               # drop video stream
                        "-acodec", "libmp3lame",
                        "-q:a", "4",         # ~128kbps — sufficient for Whisper
                        tmp.name,
                    ],
                    check=True,
                    timeout=540,             # leave headroom before soft_time_limit=580
                    capture_output=True,
                )
                tmp.seek(0)

                client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=(f"lesson_{lesson_id}.mp3", tmp, "audio/mpeg"),
                    response_format="verbose_json",
                )

            segments: list[dict] = [s.model_dump() for s in (response.segments or [])]
            vtt_content = _build_vtt(segments)
            plain_text = " ".join(
                seg["text"].strip() for seg in segments if seg.get("text")
            )

            vtt_key = f"transcripts/{lesson_id}/transcript.vtt"
            r2 = get_r2_client()
            r2.put_object(
                Bucket=settings.R2_BUCKET,
                Key=vtt_key,
                Body=io.BytesIO(vtt_content.encode()),
                ContentType="text/vtt",
            )

            existing = db.execute(
                select(LessonTranscript).where(
                    LessonTranscript.lesson_id == lesson_uuid
                )
            ).scalar_one_or_none()

            if existing is not None:
                existing.vtt_key = vtt_key
                existing.plain_text = plain_text
            else:
                db.add(
                    LessonTranscript(
                        lesson_id=lesson_uuid,
                        vtt_key=vtt_key,
                        plain_text=plain_text,
                    )
                )

            db.commit()

        record_success(rdb, "generate_transcript", lesson_id, task_id)

        # Kick off RAG indexing now that plain_text is available.
        from app.modules.rag.tasks import index_lesson
        index_lesson.delay(lesson_id)

    except Exception as exc:
        if rdb is not None and self.request.retries >= self.max_retries:
            try:
                record_failure(rdb, "generate_transcript", lesson_id, task_id, str(exc))
            except Exception:
                pass
        raise self.retry(exc=exc, countdown=media_backoff(self.request.retries)) from exc
