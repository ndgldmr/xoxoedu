"""Celery tasks for async AI usage logging and quiz feedback generation."""

from __future__ import annotations

import json
import re

from app.worker.celery_app import celery_app
from app.worker.retry import ai_backoff


def _parse_feedback_json(content: str, expected_count: int) -> list[str]:
    """Extract per-question feedback strings from an LLM JSON response.

    Handles common LLM quirks: markdown code fences, leading prose, and
    responses that contain fewer items than expected (padded with ``""``).

    Args:
        content: Raw text returned by the LLM.
        expected_count: Number of questions; used to pad short responses.

    Returns:
        A list of ``expected_count`` feedback strings (may be empty strings).
    """
    try:
        text = re.sub(r"```(?:json)?\s*", "", content).strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return [""] * expected_count
        items: list = json.loads(text[start : end + 1])
        result = [
            str(item.get("feedback", "")) if isinstance(item, dict) else ""
            for item in items[:expected_count]
        ]
        # Pad if the LLM returned fewer items than questions
        result += [""] * (expected_count - len(result))
        return result
    except Exception:
        return [""] * expected_count


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=3,
    soft_time_limit=15,
    time_limit=20,
)
def log_ai_usage(
    self,
    user_id: str | None,
    course_id: str | None,
    feature: str,
    tokens_in: int,
    tokens_out: int,
    model: str,
) -> None:
    """Persist an AI usage record to ``ai_usage_logs``.

    Runs asynchronously after the LLM call completes so the hot request path
    is never blocked by a Postgres write.  Uses a synchronous session because
    Celery workers run outside of asyncio.

    Retries up to 3 times with exponential backoff (30 s → 60 s → 120 s) on
    transient DB failures.

    Args:
        user_id: String UUID of the user who triggered the call, or ``None``.
        course_id: String UUID of the associated course, or ``None``.
        feature: Short tag identifying the feature (e.g. ``"quiz_feedback"``).
        tokens_in: Prompt token count reported by the provider.
        tokens_out: Completion token count reported by the provider.
        model: Full model identifier used for the call.
    """
    try:
        import uuid as _uuid

        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.db.models.ai import AIUsageLog

        engine = create_engine(settings.DATABASE_URL_SYNC)
        with Session(engine) as db:
            db.add(
                AIUsageLog(
                    user_id=_uuid.UUID(user_id) if user_id else None,
                    course_id=_uuid.UUID(course_id) if course_id else None,
                    feature=feature,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    model=model,
                )
            )
            db.commit()

    except Exception as exc:
        raise self.retry(exc=exc, countdown=ai_backoff(self.request.retries)) from exc


@celery_app.task(  # type: ignore[misc]
    bind=True,
    ignore_result=True,
    max_retries=3,
    soft_time_limit=150,
    time_limit=180,
)
def generate_quiz_feedback(self, submission_id: str) -> None:
    """Generate AI feedback for each question in a quiz submission.

    Loads the submission, checks the course AI config, then makes a single
    LLM call for all questions using ``litellm.completion`` (sync).  The
    response is expected to be a JSON array of ``{"feedback": "..."}`` objects,
    one per question in order.  Malformed responses fall back to empty strings.
    DB errors trigger a Celery retry with exponential backoff.

    Idempotency: if any feedback rows already exist for the submission, the task
    returns immediately (the single-call design is all-or-nothing on first run).

    Task status is recorded in Redis under
    ``task:status:quiz_feedback:{submission_id}`` **only when the LLM call is
    actually attempted** — after all early-return guard checks pass.  Early
    returns (submission missing, feedback already written, AI disabled) leave
    no status record so the key is not stuck in "started".

    Retries up to 3 times with exponential backoff (30 s → 60 s → 120 s) on
    transient DB failures.  LLM call failures are caught internally and result
    in empty feedback strings rather than retries (graceful AI degradation).

    Args:
        submission_id: String UUID of the ``QuizSubmission`` to process.
    """
    # rdb is initialised inside the try block; held here so the except handler
    # can reference it for failure recording without a NameError.
    rdb = None
    task_id = str(self.request.id)

    try:
        import uuid as _uuid

        import litellm
        import redis as sync_redis
        from sqlalchemy import create_engine, func, select
        from sqlalchemy.orm import Session, joinedload

        from app.config import settings
        from app.db.models.ai import AIUsageBudget
        from app.db.models.course import Chapter, Lesson
        from app.db.models.quiz import Quiz, QuizFeedback, QuizSubmission
        from app.modules.ai.service import render_prompt
        from app.worker.task_status import record_failure, record_started, record_success

        rdb = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)

        submission_uuid = _uuid.UUID(submission_id)
        engine = create_engine(settings.DATABASE_URL_SYNC)

        with Session(engine) as db:
            # Load submission with quiz and all questions in one query
            sub = db.execute(
                select(QuizSubmission)
                .where(QuizSubmission.id == submission_uuid)
                .options(joinedload(QuizSubmission.quiz).joinedload(Quiz.questions))
            ).unique().scalar_one_or_none()

            if sub is None:
                return

            # Idempotency: skip if feedback was already written (e.g. prior retry)
            existing_count: int = db.execute(
                select(func.count()).where(
                    QuizFeedback.submission_id == submission_uuid
                )
            ).scalar_one()
            if existing_count > 0:
                return

            # Resolve course_id: quiz → lesson → chapter → course
            course_id = db.execute(
                select(Chapter.course_id)
                .join(Lesson, Lesson.chapter_id == Chapter.id)
                .join(Quiz, Quiz.lesson_id == Lesson.id)
                .where(Quiz.id == sub.quiz_id)
            ).scalar_one_or_none()

            # Load AI config; missing row means platform defaults (ai_enabled=True)
            ai_config = None
            if course_id is not None:
                ai_config = db.execute(
                    select(AIUsageBudget).where(AIUsageBudget.course_id == course_id)
                ).scalar_one_or_none()

            if ai_config is not None and not ai_config.ai_enabled:
                return

            # Build per-question context for the prompt — incorrect answers only.
            # Correct answers need no feedback and skipping them reduces LLM cost.
            incorrect_questions = []
            questions_data = []
            for question in sub.quiz.questions:
                student_answers: list[str] = sub.answers.get(str(question.id), [])
                if question.kind == "single_choice":
                    is_correct = (
                        len(student_answers) == 1
                        and student_answers[0] in question.correct_answers
                    )
                else:
                    is_correct = set(student_answers) == set(question.correct_answers)

                if is_correct:
                    continue  # no feedback needed for correct answers

                incorrect_questions.append(question)
                questions_data.append({
                    "stem": question.stem,
                    "options": question.options,
                    "correct_answers": question.correct_answers,
                    "student_answers": student_answers,
                    "is_correct": False,
                })

            if not questions_data:
                # All questions answered correctly — nothing to explain.
                return

            # All guards passed — record that we are now doing real work.
            record_started(rdb, "quiz_feedback", submission_id, task_id)

            tone = ai_config.tone if ai_config else "encouraging"
            override = ai_config.system_prompt_override if ai_config else None
            model = settings.AI_MODEL
            user_id_str = str(sub.user_id)

            system_msg = render_prompt(
                "base.j2", tone=tone, system_prompt_override=override
            )
            user_msg = render_prompt("quiz_feedback.j2", questions=questions_data)

            call_kwargs: dict = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.3,
            }
            if settings.GEMINI_API_KEY:
                call_kwargs["api_key"] = settings.GEMINI_API_KEY

            feedback_texts = [""] * len(questions_data)
            tokens_in = 0
            tokens_out = 0
            try:
                response = litellm.completion(**call_kwargs)
                content = response.choices[0].message.content or ""
                usage = response.usage
                if usage:
                    tokens_in = usage.prompt_tokens or 0
                    tokens_out = usage.completion_tokens or 0
                feedback_texts = _parse_feedback_json(content, len(questions_data))
            except Exception:
                import logging, traceback
                logging.getLogger(__name__).error(
                    "LLM call failed for submission %s:\n%s",
                    submission_id, traceback.format_exc()
                )

            for question, feedback_text in zip(incorrect_questions, feedback_texts):
                db.add(
                    QuizFeedback(
                        submission_id=submission_uuid,
                        question_id=question.id,
                        feedback_text=feedback_text,
                    )
                )

            db.commit()

        record_success(rdb, "quiz_feedback", submission_id, task_id)

        if tokens_in > 0 or tokens_out > 0:
            log_ai_usage.delay(
                user_id=user_id_str,
                course_id=str(course_id) if course_id else None,
                feature="quiz_feedback",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
            )

    except Exception as exc:
        if rdb is not None and self.request.retries >= self.max_retries:
            try:
                record_failure(rdb, "quiz_feedback", submission_id, task_id, str(exc))
            except Exception:
                pass
        raise self.retry(exc=exc, countdown=ai_backoff(self.request.retries)) from exc
