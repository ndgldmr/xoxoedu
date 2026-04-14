"""Unit tests for VTT generation and Mux webhook signature verification."""

import hashlib
import hmac
import time

from app.modules.video.tasks import _build_vtt, _seconds_to_vtt_timestamp


# ── _seconds_to_vtt_timestamp ─────────────────────────────────────────────────

def test_seconds_to_vtt_timestamp_zero() -> None:
    assert _seconds_to_vtt_timestamp(0) == "00:00:00.000"


def test_seconds_to_vtt_timestamp_sub_minute() -> None:
    assert _seconds_to_vtt_timestamp(5.5) == "00:00:05.500"


def test_seconds_to_vtt_timestamp_minutes() -> None:
    assert _seconds_to_vtt_timestamp(90.25) == "00:01:30.250"


def test_seconds_to_vtt_timestamp_hours() -> None:
    assert _seconds_to_vtt_timestamp(3661.0) == "01:01:01.000"


# ── _build_vtt ────────────────────────────────────────────────────────────────

def test_build_vtt_header() -> None:
    """VTT output always starts with 'WEBVTT'."""
    result = _build_vtt([])
    assert result.startswith("WEBVTT")


def test_build_vtt_single_segment() -> None:
    segments = [{"start": 0.0, "end": 3.5, "text": " Hello world."}]
    result = _build_vtt(segments)
    assert "00:00:00.000 --> 00:00:03.500" in result
    assert "Hello world." in result


def test_build_vtt_multiple_segments_ordered() -> None:
    segments = [
        {"start": 0.0, "end": 2.0, "text": " First."},
        {"start": 2.0, "end": 5.0, "text": " Second."},
    ]
    result = _build_vtt(segments)
    lines = result.splitlines()
    # Cue indices should appear in order
    assert "1" in lines
    assert "2" in lines
    first_cue_pos = lines.index("1")
    second_cue_pos = lines.index("2")
    assert first_cue_pos < second_cue_pos


def test_build_vtt_strips_leading_whitespace_from_text() -> None:
    segments = [{"start": 0.0, "end": 1.0, "text": "   Trimmed text."}]
    result = _build_vtt(segments)
    assert "Trimmed text." in result
    # Leading spaces should not appear before the cue text
    for line in result.splitlines():
        if "Trimmed" in line:
            assert not line.startswith(" ")


def test_build_vtt_empty_segments() -> None:
    """Empty segment list produces a valid but cue-free VTT file."""
    result = _build_vtt([])
    assert result.strip() == "WEBVTT"


# ── Webhook signature verification ────────────────────────────────────────────

def _make_mux_signature(body: bytes, secret: str) -> str:
    """Helper: build a valid mux-signature header value."""
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.".encode() + body
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def test_verify_mux_signature_valid(monkeypatch) -> None:
    from app.modules.video.router import _verify_mux_signature

    monkeypatch.setattr("app.modules.video.router.settings.MUX_WEBHOOK_SECRET", "testsecret")
    body = b'{"type":"video.asset.ready"}'
    header = _make_mux_signature(body, "testsecret")
    # Should not raise
    _verify_mux_signature(body, header)


def test_verify_mux_signature_wrong_secret(monkeypatch) -> None:
    from app.core.exceptions import InvalidWebhookSignature
    from app.modules.video.router import _verify_mux_signature

    monkeypatch.setattr("app.modules.video.router.settings.MUX_WEBHOOK_SECRET", "testsecret")
    body = b'{"type":"video.asset.ready"}'
    header = _make_mux_signature(body, "wrongsecret")
    import pytest
    with pytest.raises(InvalidWebhookSignature):
        _verify_mux_signature(body, header)


def test_verify_mux_signature_empty_header(monkeypatch) -> None:
    from app.core.exceptions import InvalidWebhookSignature
    from app.modules.video.router import _verify_mux_signature

    monkeypatch.setattr("app.modules.video.router.settings.MUX_WEBHOOK_SECRET", "testsecret")
    import pytest
    with pytest.raises(InvalidWebhookSignature):
        _verify_mux_signature(b"body", "")


def test_verify_mux_signature_malformed_header(monkeypatch) -> None:
    from app.core.exceptions import InvalidWebhookSignature
    from app.modules.video.router import _verify_mux_signature

    monkeypatch.setattr("app.modules.video.router.settings.MUX_WEBHOOK_SECRET", "testsecret")
    import pytest
    with pytest.raises(InvalidWebhookSignature):
        _verify_mux_signature(b"body", "not-a-valid-header")
