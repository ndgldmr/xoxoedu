"""Unit tests for placement scoring and band-mapping pure helpers.

All tests are synchronous and require no database connection.  They directly
import and exercise ``_compute_band`` and ``_score_placement`` from the
placement service module.
"""

import pytest

from app.modules.placement.service import (
    _PLACEMENT_QUESTIONS,
    _compute_band,
    _score_placement,
)

# ── Band mapping ───────────────────────────────────────────────────────────────

def test_band_score_0_is_oc() -> None:
    label, code = _compute_band(0)
    assert label == "a2_or_below"
    assert code == "OC"


def test_band_score_5_is_oc() -> None:
    label, code = _compute_band(5)
    assert label == "a2_or_below"
    assert code == "OC"


def test_band_score_12_is_oc() -> None:
    label, code = _compute_band(12)
    assert label == "a2_or_below"
    assert code == "OC"


def test_band_score_13_is_pt() -> None:
    label, code = _compute_band(13)
    assert label == "b1_to_b2"
    assert code == "PT"


def test_band_score_19_is_pt() -> None:
    label, code = _compute_band(19)
    assert label == "b1_to_b2"
    assert code == "PT"


def test_band_score_20_is_fe() -> None:
    label, code = _compute_band(20)
    assert label == "b2_plus"
    assert code == "FE"


def test_band_score_25_is_fe() -> None:
    label, code = _compute_band(25)
    assert label == "b2_plus"
    assert code == "FE"


def test_band_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        _compute_band(26)

    with pytest.raises(ValueError):
        _compute_band(-1)


# ── Score computation ──────────────────────────────────────────────────────────

def _all_correct_answers() -> dict[str, list[str]]:
    """Build an answers dict with every question answered correctly."""
    return {q["id"]: [q["correct"]] for q in _PLACEMENT_QUESTIONS}


def _all_wrong_answers() -> dict[str, list[str]]:
    """Build an answers dict with every question answered with a wrong option."""
    wrong: dict[str, list[str]] = {}
    for q in _PLACEMENT_QUESTIONS:
        other = next(o["id"] for o in q["options"] if o["id"] != q["correct"])
        wrong[q["id"]] = [other]
    return wrong


def test_score_all_correct() -> None:
    raw, max_score = _score_placement(_all_correct_answers())
    assert raw == 25
    assert max_score == 25


def test_score_all_wrong() -> None:
    raw, max_score = _score_placement(_all_wrong_answers())
    assert raw == 0
    assert max_score == 25


def test_score_missing_question_is_zero() -> None:
    """An unanswered question should count as 0, not raise an error."""
    answers = _all_correct_answers()
    del answers["q01"]
    raw, max_score = _score_placement(answers)
    assert raw == 24
    assert max_score == 25


def test_score_multi_option_is_wrong() -> None:
    """Submitting two options for a single-choice question scores as 0."""
    q = _PLACEMENT_QUESTIONS[0]
    other = next(o["id"] for o in q["options"] if o["id"] != q["correct"])
    answers = _all_correct_answers()
    answers[q["id"]] = [q["correct"], other]  # two options submitted
    raw, _ = _score_placement(answers)
    # q01 is now wrong; remaining 24 are correct
    assert raw == 24


def test_score_empty_option_list_is_wrong() -> None:
    """Submitting an empty list for a question scores as 0."""
    answers = _all_correct_answers()
    answers["q01"] = []
    raw, _ = _score_placement(answers)
    assert raw == 24


def test_score_max_score_always_equals_question_count() -> None:
    """max_score must always equal the number of questions, regardless of answers."""
    _, max_score = _score_placement({})
    assert max_score == len(_PLACEMENT_QUESTIONS)
