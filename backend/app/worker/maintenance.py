"""Periodic maintenance tasks run by the Celery beat scheduler.

Each task here is a lightweight coordinator: it queries the database and
enqueues work tasks rather than doing heavy lifting itself.  All tasks have
``max_retries=0`` because beat fires them on a fixed schedule — a failure
will be retried on the next beat tick rather than immediately.

Tasks in this module are registered via a direct import in ``celery_app.py``
(not via ``autodiscover_tasks``, which only finds ``tasks.py`` files).
"""

from __future__ import annotations

from app.worker.celery_app import celery_app

# ── Stuck-transcript recovery ──────────────────────────────────────────────────

_STUCK_AFTER_SECONDS = 2 * 3600   # 2 hours — past the normal processing window
_STARTED_RECENCY_SECONDS = 2 * 3600  # skip if a task started within the last 2 h


@celery_app.task(bind=True, ignore_result=True, max_retries=0)  # type: ignore[misc]
def retry_stuck_transcriptions(self) -> None:
    """Re-trigger transcription for video lessons whose transcript is missing.

    A transcript is considered stuck when:
    - The lesson has a ``mux_playback_id`` (video is ready on Mux).
    - There is no ``LessonTranscript`` row for the lesson.
    - The lesson was created more than 2 hours ago (past the normal processing
      window, so the initial task was either lost or silently failed).

    Idempotency guard: if ``task:status:generate_transcript:<lesson_id>``
    records a ``"started"`` status with a timestamp less than 2 hours old,
    the lesson is skipped — transcription is already in progress.

    This task is designed to run every hour via celery beat.
    """
    import time
    from datetime import datetime, timedelta, timezone

    import redis as sync_redis
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import settings
    from app.db.models.course import Lesson, LessonTranscript
    from app.modules.video.tasks import generate_transcript
    from app.worker.task_status import get_status

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_STUCK_AFTER_SECONDS)
    engine = create_engine(settings.DATABASE_URL_SYNC)
    rdb = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)

    with Session(engine) as db:
        stuck_ids = db.execute(
            select(Lesson.id)
            .outerjoin(LessonTranscript, LessonTranscript.lesson_id == Lesson.id)
            .where(
                Lesson.mux_playback_id.is_not(None),
                LessonTranscript.lesson_id.is_(None),
                Lesson.created_at < cutoff,
            )
        ).scalars().all()

    now = time.time()
    enqueued = 0
    for lesson_id in stuck_ids:
        status = get_status(rdb, "generate_transcript", str(lesson_id))
        if (
            status is not None
            and status.get("status") == "started"
            and (now - status.get("ts", 0)) < _STARTED_RECENCY_SECONDS
        ):
            # Transcription is actively running — do not re-enqueue.
            continue

        generate_transcript.delay(str(lesson_id))
        enqueued += 1

    if enqueued:
        import logging
        logging.getLogger(__name__).info(
            "retry_stuck_transcriptions: re-enqueued %d lesson(s)", enqueued
        )
