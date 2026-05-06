"""Unit tests for live session iCal generation and reminder scheduling logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.modules.batches.ical import _SessionData, _escape_text, _fold, _fmt_dt, build_ical


# ── iCal helpers ───────────────────────────────────────────────────────────────

class TestEscapeText:
    def test_plain_string_unchanged(self) -> None:
        assert _escape_text("Hello World") == "Hello World"

    def test_backslash_escaped(self) -> None:
        assert _escape_text("a\\b") == "a\\\\b"

    def test_semicolon_escaped(self) -> None:
        assert _escape_text("a;b") == "a\\;b"

    def test_comma_escaped(self) -> None:
        assert _escape_text("a,b") == "a\\,b"

    def test_newline_escaped(self) -> None:
        assert _escape_text("line1\nline2") == "line1\\nline2"

    def test_multiple_specials(self) -> None:
        result = _escape_text("foo,bar;baz\\qux")
        assert result == "foo\\,bar\\;baz\\\\qux"


class TestFmtDt:
    def test_utc_datetime_formatted(self) -> None:
        dt = datetime(2026, 6, 15, 14, 30, 0, tzinfo=UTC)
        assert _fmt_dt(dt) == "20260615T143000Z"

    def test_non_utc_converted_to_utc(self) -> None:
        # EST = UTC-5; 09:00 EST → 14:00 UTC
        est = timezone(timedelta(hours=-5))
        dt = datetime(2026, 6, 15, 9, 0, 0, tzinfo=est)
        assert _fmt_dt(dt) == "20260615T140000Z"


class TestFold:
    def test_short_line_unchanged(self) -> None:
        result = _fold("BEGIN:VCALENDAR")
        assert result == "BEGIN:VCALENDAR\r\n"

    def test_long_line_folded(self) -> None:
        # 80-char line; should be split at 75 with CRLF+SP continuation
        line = "SUMMARY:" + "A" * 72  # 8 + 72 = 80 chars
        result = _fold(line)
        assert "\r\n " in result
        # Reconstructing should equal the original line
        unfolded = result.replace("\r\n ", "").rstrip("\r\n")
        assert unfolded == line

    def test_fold_at_utf8_boundary(self) -> None:
        # Use multi-byte chars to ensure we don't split inside one
        line = "SUMMARY:" + "é" * 40  # 'é' is 2 bytes; 8 + 80 bytes total
        result = _fold(line)
        # All continuation lines must be valid UTF-8 (no split mid-char)
        for part in result.split("\r\n "):
            part.strip("\r\n").encode("utf-8")  # must not raise

    def test_very_long_line_multi_fold(self) -> None:
        line = "DESCRIPTION:" + "X" * 300
        result = _fold(line)
        # Every physical line in the output must be ≤ 75 bytes (excluding CRLF)
        for physical_line in result.split("\r\n"):
            if physical_line:  # skip empty trailing segment
                assert len(physical_line.encode("utf-8")) <= 75


class TestBuildIcal:
    def _make_session(self, **kwargs: object) -> _SessionData:
        return _SessionData(
            session_id=kwargs.get("session_id", "aaaaaaaa-0000-0000-0000-000000000001"),  # type: ignore[arg-type]
            title=kwargs.get("title", "Week 1 Intro"),  # type: ignore[arg-type]
            description=kwargs.get("description", None),  # type: ignore[arg-type]
            starts_at=kwargs.get("starts_at", datetime(2026, 7, 1, 10, 0, tzinfo=UTC)),  # type: ignore[arg-type]
            ends_at=kwargs.get("ends_at", datetime(2026, 7, 1, 11, 0, tzinfo=UTC)),  # type: ignore[arg-type]
            join_url=kwargs.get("join_url", None),  # type: ignore[arg-type]
        )

    def test_vcalendar_wrapper_present(self) -> None:
        out = build_ical([])
        assert "BEGIN:VCALENDAR" in out
        assert "END:VCALENDAR" in out

    def test_version_and_prodid(self) -> None:
        out = build_ical([])
        assert "VERSION:2.0" in out
        assert "PRODID:" in out

    def test_single_vevent_emitted(self) -> None:
        out = build_ical([self._make_session()])
        assert out.count("BEGIN:VEVENT") == 1
        assert out.count("END:VEVENT") == 1

    def test_uid_deterministic(self) -> None:
        s = self._make_session(session_id="test-id-123")
        out = build_ical([s])
        assert "UID:test-id-123@xoxoedu" in out

    def test_dtstart_dtend_in_utc(self) -> None:
        starts = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
        ends = datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
        out = build_ical([self._make_session(starts_at=starts, ends_at=ends)])
        assert "DTSTART:20260701T100000Z" in out
        assert "DTEND:20260701T110000Z" in out

    def test_summary_present(self) -> None:
        out = build_ical([self._make_session(title="My Session")])
        assert "SUMMARY:My Session" in out

    def test_description_omitted_when_none(self) -> None:
        out = build_ical([self._make_session(description=None)])
        assert "DESCRIPTION:" not in out

    def test_description_included_when_set(self) -> None:
        out = build_ical([self._make_session(description="Come prepared!")])
        assert "DESCRIPTION:Come prepared!" in out

    def test_url_omitted_when_none(self) -> None:
        out = build_ical([self._make_session(join_url=None)])
        assert "URL:" not in out

    def test_url_included_when_set(self) -> None:
        out = build_ical([self._make_session(join_url="https://zoom.us/j/123")])
        assert "URL:https://zoom.us/j/123" in out

    def test_multiple_sessions_produce_multiple_vevents(self) -> None:
        sessions = [self._make_session(session_id=f"id-{i}") for i in range(3)]
        out = build_ical(sessions)
        assert out.count("BEGIN:VEVENT") == 3

    def test_empty_sessions_list(self) -> None:
        out = build_ical([])
        assert "BEGIN:VEVENT" not in out
        assert "END:VCALENDAR" in out

    def test_title_with_comma_escaped(self) -> None:
        out = build_ical([self._make_session(title="Q&A, Week 1")])
        assert "SUMMARY:Q&A\\, Week 1" in out

    def test_crlf_line_endings_throughout(self) -> None:
        out = build_ical([self._make_session()])
        assert "\r\n" in out
        # No bare LF without preceding CR
        lines = out.split("\r\n")
        for line in lines:
            assert "\n" not in line


# ── Reminder scheduling ────────────────────────────────────────────────────────

class TestScheduleReminder:
    # The task is imported lazily inside _schedule_reminder so we patch it
    # at the source module (app.modules.batches.tasks), not the service module.

    def test_schedules_task_when_session_is_in_future(self) -> None:
        from app.modules.batches.live_session_service import _schedule_reminder

        future = datetime.now(UTC) + timedelta(hours=3)
        mock_result = MagicMock()
        mock_result.id = "task-abc-123"

        with patch(
            "app.modules.batches.tasks.send_live_session_reminder"
        ) as mock_task:
            mock_task.apply_async.return_value = mock_result
            result = _schedule_reminder(
                session_id=__import__("uuid").uuid4(),
                starts_at=future,
            )

        assert result == "task-abc-123"
        mock_task.apply_async.assert_called_once()
        call_kwargs = mock_task.apply_async.call_args.kwargs
        expected_eta = future - timedelta(hours=1)
        # ETA should be within a few seconds of 1 hour before start
        assert abs((call_kwargs["eta"] - expected_eta).total_seconds()) < 5

    def test_returns_none_when_session_starts_within_one_hour(self) -> None:
        from app.modules.batches.live_session_service import _schedule_reminder

        soon = datetime.now(UTC) + timedelta(minutes=30)

        with patch(
            "app.modules.batches.tasks.send_live_session_reminder"
        ) as mock_task:
            result = _schedule_reminder(
                session_id=__import__("uuid").uuid4(),
                starts_at=soon,
            )

        assert result is None
        mock_task.apply_async.assert_not_called()

    def test_returns_none_for_past_session(self) -> None:
        from app.modules.batches.live_session_service import _schedule_reminder

        past = datetime.now(UTC) - timedelta(hours=2)

        with patch(
            "app.modules.batches.tasks.send_live_session_reminder"
        ) as mock_task:
            result = _schedule_reminder(
                session_id=__import__("uuid").uuid4(),
                starts_at=past,
            )

        assert result is None
        mock_task.apply_async.assert_not_called()
