"""Unit tests for _parse_feedback_json and generate_quiz_feedback error handling."""

import uuid
from unittest.mock import MagicMock, patch

from app.modules.ai.tasks import _parse_feedback_json


# ── _parse_feedback_json ───────────────────────────────────────────────────────

def test_parse_clean_json() -> None:
    content = '[{"feedback": "Great job!"}, {"feedback": "Try again."}]'
    result = _parse_feedback_json(content, 2)
    assert result == ["Great job!", "Try again."]


def test_parse_strips_code_fence() -> None:
    content = '```json\n[{"feedback": "Nice!"}]\n```'
    result = _parse_feedback_json(content, 1)
    assert result == ["Nice!"]


def test_parse_strips_code_fence_no_language() -> None:
    content = '```\n[{"feedback": "Ok"}]\n```'
    result = _parse_feedback_json(content, 1)
    assert result == ["Ok"]


def test_parse_preamble_before_array() -> None:
    """Leading prose before the JSON array is ignored."""
    content = 'Here is the feedback:\n[{"feedback": "Well done!"}]'
    result = _parse_feedback_json(content, 1)
    assert result == ["Well done!"]


def test_parse_pads_when_llm_returns_fewer_items() -> None:
    """Short response is padded with empty strings to match expected_count."""
    content = '[{"feedback": "Only one"}]'
    result = _parse_feedback_json(content, 3)
    assert result == ["Only one", "", ""]


def test_parse_truncates_when_llm_returns_more_items() -> None:
    content = '[{"feedback": "A"}, {"feedback": "B"}, {"feedback": "C"}]'
    result = _parse_feedback_json(content, 2)
    assert result == ["A", "B"]


def test_parse_missing_feedback_key_returns_empty_string() -> None:
    content = '[{"other_key": "value"}]'
    result = _parse_feedback_json(content, 1)
    assert result == [""]


def test_parse_non_dict_items_return_empty_string() -> None:
    content = '["just a string"]'
    result = _parse_feedback_json(content, 1)
    assert result == [""]


def test_parse_invalid_json_returns_empty_strings() -> None:
    result = _parse_feedback_json("not json at all", 2)
    assert result == ["", ""]


def test_parse_empty_content_returns_empty_strings() -> None:
    result = _parse_feedback_json("", 3)
    assert result == ["", "", ""]


def test_parse_none_content_returns_empty_strings() -> None:
    """None feedback_text from LLM (coerced to empty string before calling) is handled."""
    result = _parse_feedback_json("", 1)
    assert result == [""]


# ── Task error handling ────────────────────────────────────────────────────────

_SUB_ID = str(uuid.uuid4())
_QUIZ_ID = str(uuid.uuid4())
_Q_ID = str(uuid.uuid4())
_USER_ID = str(uuid.uuid4())


def _make_submission() -> MagicMock:
    question = MagicMock()
    question.id = uuid.UUID(_Q_ID)
    question.kind = "single_choice"
    question.stem = "What is 2+2?"
    question.options = [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}]
    question.correct_answers = ["b"]

    quiz = MagicMock()
    quiz.id = uuid.UUID(_QUIZ_ID)
    quiz.questions = [question]

    sub = MagicMock()
    sub.id = uuid.UUID(_SUB_ID)
    sub.user_id = uuid.UUID(_USER_ID)
    sub.quiz_id = uuid.UUID(_QUIZ_ID)
    sub.quiz = quiz
    sub.answers = {_Q_ID: ["a"]}  # incorrect — triggers feedback generation
    return sub


def _make_db(sub: MagicMock) -> MagicMock:
    call_count = [0]

    def execute_side_effect(stmt):
        result = MagicMock()
        result.unique.return_value = result
        call_count[0] += 1
        if call_count[0] == 1:
            result.scalar_one_or_none.return_value = sub
            result.scalar_one.return_value = sub
        else:
            result.scalar_one_or_none.return_value = None
            result.scalar_one.return_value = 0  # existing_count = 0
        return result

    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.execute = MagicMock(side_effect=execute_side_effect)
    return db


def test_llm_exception_stores_empty_feedback() -> None:
    """Any LLM exception is caught; empty feedback rows are still written."""
    sub = _make_submission()
    db = _make_db(sub)
    added_rows: list = []
    db.add = MagicMock(side_effect=added_rows.append)

    with (
        patch("sqlalchemy.create_engine"),
        patch("sqlalchemy.orm.Session", return_value=db),
        patch("litellm.completion", side_effect=Exception("provider down")),
        patch("app.modules.ai.tasks.log_ai_usage"),
        patch("redis.from_url", return_value=MagicMock()),
    ):
        from app.modules.ai.tasks import generate_quiz_feedback
        result = generate_quiz_feedback.apply(args=[_SUB_ID])

    assert result.state != "FAILURE"
    assert len(added_rows) == 1
    assert added_rows[0].feedback_text == ""


def test_missing_submission_returns_silently() -> None:
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    r = MagicMock()
    r.unique.return_value = r
    r.scalar_one_or_none.return_value = None
    db.execute = MagicMock(return_value=r)

    with (
        patch("sqlalchemy.create_engine"),
        patch("sqlalchemy.orm.Session", return_value=db),
        patch("redis.from_url", return_value=MagicMock()),
    ):
        from app.modules.ai.tasks import generate_quiz_feedback
        task_result = generate_quiz_feedback.apply(
            args=["00000000-0000-0000-0000-000000000000"]
        )

    assert task_result.state != "FAILURE"
    db.add.assert_not_called()
