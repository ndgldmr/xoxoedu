"""Unit tests for Jinja2 prompt template rendering."""

from app.modules.ai.service import render_prompt


def test_base_template_default_tone() -> None:
    """Base template renders with the default encouraging tone."""
    result = render_prompt("base.j2")
    assert "encouraging" in result


def test_base_template_custom_tone() -> None:
    result = render_prompt("base.j2", tone="strict")
    assert "strict" in result
    assert "encouraging" not in result


def test_base_template_system_prompt_override() -> None:
    """When system_prompt_override is set, it replaces the default text entirely."""
    override = "You are a pirate who teaches math."
    result = render_prompt("base.j2", system_prompt_override=override)
    assert result.strip() == override
    assert "encouraging" not in result


def test_base_template_override_takes_precedence_over_tone() -> None:
    """system_prompt_override wins even when tone is also supplied."""
    override = "Custom prompt."
    result = render_prompt("base.j2", tone="neutral", system_prompt_override=override)
    assert result.strip() == override


# ── quiz_feedback.j2 ──────────────────────────────────────────────────────────

def _make_question(
    stem: str = "What is the capital of France?",
    options: list | None = None,
    correct_answers: list[str] | None = None,
    student_answers: list[str] | None = None,
    is_correct: bool = True,
) -> dict:
    return {
        "stem": stem,
        "options": options or [{"id": "a", "text": "Paris"}, {"id": "b", "text": "London"}],
        "correct_answers": correct_answers or ["a"],
        "student_answers": student_answers if student_answers is not None else ["a"],
        "is_correct": is_correct,
    }


def test_quiz_feedback_injects_question_stem() -> None:
    result = render_prompt("quiz_feedback.j2", questions=[_make_question()])
    assert "What is the capital of France?" in result


def test_quiz_feedback_injects_all_options() -> None:
    q = _make_question(options=[{"id": "a", "text": "Paris"}, {"id": "b", "text": "London"}, {"id": "c", "text": "Berlin"}])
    result = render_prompt("quiz_feedback.j2", questions=[q])
    assert "Paris" in result
    assert "London" in result
    assert "Berlin" in result


def test_quiz_feedback_injects_correct_answers() -> None:
    q = _make_question(correct_answers=["a", "c"], student_answers=["b"], is_correct=False)
    result = render_prompt("quiz_feedback.j2", questions=[q])
    assert "a, c" in result


def test_quiz_feedback_injects_student_answers() -> None:
    q = _make_question(student_answers=["b"], is_correct=False)
    result = render_prompt("quiz_feedback.j2", questions=[q])
    assert "b" in result


def test_quiz_feedback_correct_outcome_label() -> None:
    result = render_prompt("quiz_feedback.j2", questions=[_make_question(is_correct=True)])
    assert "Correct" in result


def test_quiz_feedback_incorrect_outcome_label() -> None:
    q = _make_question(student_answers=["b"], is_correct=False)
    result = render_prompt("quiz_feedback.j2", questions=[q])
    assert "Incorrect" in result


def test_quiz_feedback_no_answer_renders_none_label() -> None:
    """An empty student_answers list renders as 'none'."""
    q = _make_question(student_answers=[], is_correct=False)
    result = render_prompt("quiz_feedback.j2", questions=[q])
    assert "none" in result


def test_quiz_feedback_multiple_questions_all_present() -> None:
    """All question stems appear when multiple questions are passed."""
    questions = [
        _make_question(stem="Question one?"),
        _make_question(stem="Question two?"),
        _make_question(stem="Question three?"),
    ]
    result = render_prompt("quiz_feedback.j2", questions=questions)
    assert "Question one?" in result
    assert "Question two?" in result
    assert "Question three?" in result


def test_quiz_feedback_json_instruction_present() -> None:
    """The JSON array instruction is always in the rendered prompt."""
    result = render_prompt("quiz_feedback.j2", questions=[_make_question()])
    assert '{"feedback":' in result or '"feedback"' in result
