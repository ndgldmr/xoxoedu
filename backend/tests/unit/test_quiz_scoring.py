"""Unit tests for pure quiz scoring functions."""

from types import SimpleNamespace

from app.modules.quizzes.service import (
    _score_multi_choice,
    _score_single_choice,
    _score_submission,
)

# ── _score_single_choice ───────────────────────────────────────────────────────

def test_single_choice_correct() -> None:
    """Selecting the one correct option awards full points."""
    assert _score_single_choice(["a"], ["a"], points=2) == 2


def test_single_choice_wrong() -> None:
    assert _score_single_choice(["a"], ["b"], points=2) == 0


def test_single_choice_multi_given_is_wrong() -> None:
    """Selecting multiple options for a single-choice question scores zero."""
    assert _score_single_choice(["a"], ["a", "b"], points=2) == 0


def test_single_choice_empty_given() -> None:
    assert _score_single_choice(["a"], [], points=1) == 0


# ── _score_multi_choice ────────────────────────────────────────────────────────

def test_multi_choice_exact_match() -> None:
    """Selecting all correct options and no extras awards full points."""
    assert _score_multi_choice(["a", "b"], ["a", "b"], points=3) == 3


def test_multi_choice_order_independent() -> None:
    """Order of selected options does not affect scoring."""
    assert _score_multi_choice(["a", "b"], ["b", "a"], points=3) == 3


def test_multi_choice_partial_gives_zero() -> None:
    """Selecting only a subset of correct answers scores zero (no partial credit)."""
    assert _score_multi_choice(["a", "b"], ["a"], points=3) == 0


def test_multi_choice_extra_selected_gives_zero() -> None:
    """Selecting extra options in addition to correct ones scores zero."""
    assert _score_multi_choice(["a", "b"], ["a", "b", "c"], points=3) == 0


def test_multi_choice_empty_given() -> None:
    assert _score_multi_choice(["a", "b"], [], points=3) == 0


# ── _score_submission ──────────────────────────────────────────────────────────

def _make_question(**overrides) -> SimpleNamespace:
    """Build a minimal question-like object for scoring tests."""
    defaults = {
        "id": "q1",
        "kind": "single_choice",
        "correct_answers": ["a"],
        "points": 1,
    }
    defaults.update(overrides)
    ns = SimpleNamespace(**defaults)
    # _score_submission uses str(q.id) as the answers dict key
    ns.id = defaults["id"]
    return ns


def test_score_submission_all_correct() -> None:
    """Perfect answers yield score == max_score."""
    questions = [
        _make_question(id="q1", kind="single_choice", correct_answers=["a"], points=1),
        _make_question(id="q2", kind="multi_choice", correct_answers=["b", "c"], points=2),
    ]
    answers = {"q1": ["a"], "q2": ["b", "c"]}
    score, max_score = _score_submission(questions, answers)  # type: ignore[arg-type]
    assert score == 3
    assert max_score == 3


def test_score_submission_all_wrong() -> None:
    questions = [
        _make_question(id="q1", kind="single_choice", correct_answers=["a"], points=1),
    ]
    score, max_score = _score_submission(questions, {"q1": ["b"]})  # type: ignore[arg-type]
    assert score == 0
    assert max_score == 1


def test_score_submission_empty_answers() -> None:
    """Missing answers for all questions yields score 0."""
    questions = [
        _make_question(id="q1", kind="single_choice", correct_answers=["a"], points=1),
    ]
    score, max_score = _score_submission(questions, {})  # type: ignore[arg-type]
    assert score == 0
    assert max_score == 1


def test_score_submission_mixed() -> None:
    """A mix of correct and incorrect answers is summed correctly."""
    questions = [
        _make_question(id="q1", kind="single_choice", correct_answers=["a"], points=1),
        _make_question(id="q2", kind="single_choice", correct_answers=["x"], points=2),
    ]
    answers = {"q1": ["a"], "q2": ["wrong"]}
    score, max_score = _score_submission(questions, answers)  # type: ignore[arg-type]
    assert score == 1
    assert max_score == 3
