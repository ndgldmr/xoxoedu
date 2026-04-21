from celery import Celery
from kombu import Exchange, Queue

from app.config import settings

# ── Broker / backend resolution ────────────────────────────────────────────────
# Fall back to REDIS_URL so the stack boots without configuration changes when
# CELERY_BROKER_URL / CELERY_RESULT_BACKEND are not set (e.g. local dev without
# RabbitMQ, or the test suite).
_broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
_result_backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

celery_app = Celery("xoxoedu", broker=_broker_url, backend=_result_backend)

# ── Dead-letter exchange ───────────────────────────────────────────────────────
# All five worker queues forward rejected messages to this exchange.
# Messages arrive here when:
#   - A worker process is killed mid-task (SIGKILL, OOM) — requires
#     task_reject_on_worker_lost=True (set below).
#   - A message's per-queue TTL expires (x-message-ttl, reserved for Sprint A3+).
#   - A message exceeds the queue's x-max-length cap (reserved for Sprint A3+).
#
# NOTE (deployment): RabbitMQ queue arguments cannot be changed after declaration.
# If the five queues already exist from a previous deploy (Sprint A2), they must
# be drained and deleted via the management UI (http://localhost:15672) or
# rabbitmqctl before bringing up the Sprint A3 containers.  Local dev is
# unaffected when the volumes are wiped (docker-compose down -v).
_dead_letter_exchange = Exchange("dead_letter", type="fanout", durable=True)

_DLX_ARGS = {"x-dead-letter-exchange": "dead_letter"}

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Reject (rather than requeue) a task message when the worker process
    # executing it is killed before it can send an ack.  Combined with
    # task_acks_late=True, this routes "crashed worker" messages to the DLX
    # instead of silently requeuing them, which could cause poison pills to
    # loop forever.  Long-running media tasks killed by OOM are recovered by
    # the retry_stuck_transcriptions beat task: worst-case re-enqueue lag is
    # the 2-hour stuck threshold plus one beat interval (up to 3 hours total).
    task_reject_on_worker_lost=True,

    # ── Queue declarations ─────────────────────────────────────────────────────
    # Explicit durable declarations with DLX arguments.  The dead_letter queue
    # is consumed only by operations tooling (Flower, manual drain scripts) —
    # no worker pool consumes it automatically.
    task_queues=[
        Queue("critical",    durable=True, queue_arguments=_DLX_ARGS),
        Queue("bulk_email",  durable=True, queue_arguments=_DLX_ARGS),
        Queue("ai",          durable=True, queue_arguments=_DLX_ARGS),
        Queue("media",       durable=True, queue_arguments=_DLX_ARGS),
        Queue("indexing",    durable=True, queue_arguments=_DLX_ARGS),
        Queue("dead_letter", _dead_letter_exchange, durable=True),
    ],

    # Unrouted tasks fall to critical so they execute rather than queue silently
    # in a queue with no consumer.  Every task must have an explicit entry in
    # task_routes; this is a safety net, not a design intent.
    task_default_queue="critical",

    task_routes={
        # ── critical ── low-latency transactional email; always has capacity
        "app.modules.auth.tasks.send_verification_email":              {"queue": "critical"},
        "app.modules.auth.tasks.send_password_reset_email":            {"queue": "critical"},
        "app.modules.notifications.tasks.send_notification_email":     {"queue": "critical"},
        # ── bulk_email ── announcement fan-out; throughput over latency
        "app.modules.admin.tasks.send_announcement_emails":       {"queue": "bulk_email"},
        "app.modules.admin.tasks.send_announcement_email_batch":  {"queue": "bulk_email"},
        # ── ai ── LLM calls; rate-limited by provider, moderate concurrency
        "app.modules.ai.tasks.log_ai_usage":          {"queue": "ai"},
        "app.modules.ai.tasks.generate_quiz_feedback": {"queue": "ai"},
        # ── media ── CPU/memory-heavy; low concurrency, long time limits
        "app.modules.video.tasks.generate_transcript":            {"queue": "media"},
        "app.modules.certificates.tasks.generate_certificate_pdf": {"queue": "media"},
        # ── indexing ── embedding + pgvector writes; independent of media
        "app.modules.rag.tasks.index_lesson": {"queue": "indexing"},
        # ── maintenance ── beat-scheduled recovery tasks; routed to critical
        # so they execute promptly and never compete with heavy workloads.
        "app.worker.maintenance.retry_stuck_transcriptions": {"queue": "critical"},
    },

    # ── RabbitMQ / AMQP reliability ────────────────────────────────────────────
    # Safe to include when CELERY_BROKER_URL points at Redis — the Redis
    # transport silently ignores keys it does not recognise.

    broker_heartbeat=60,
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,

    broker_transport_options={
        "confirm_publish": True,
    },

    task_publish_retry=True,
    task_publish_retry_policy={
        "max_retries": 3,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    },

    # ── Celery beat schedule ───────────────────────────────────────────────────
    # Tasks run by the worker-beat service (see docker-compose.yml).
    # The schedule file is persisted in a named Docker volume so that beat
    # correctly tracks last-run times across container restarts.
    beat_schedule={
        "retry-stuck-transcriptions": {
            "task": "app.worker.maintenance.retry_stuck_transcriptions",
            "schedule": 3600.0,  # every hour
        },
    },
)

celery_app.autodiscover_tasks([
    "app.modules.auth",
    "app.modules.certificates",
    "app.modules.admin",
    "app.modules.ai",
    "app.modules.video",
    "app.modules.rag",
    "app.modules.notifications",
])

# Maintenance tasks live outside the module tree autodiscover_tasks scans
# (it only finds tasks.py files).  Import explicitly to register them.
import app.worker.maintenance  # noqa: E402, F401
