"""RFC 5545 iCalendar builder for live session exports.

Generates a minimal but spec-compliant VCALENDAR/VEVENT document.  The output
imports cleanly into Google Calendar and Apple Calendar.

RFC 5545 key constraints respected here:
- Line length capped at 75 octets; long lines are folded with CRLF + single space.
- DTSTART / DTEND values use UTC form (suffix ``Z``) so no VTIMEZONE component
  is required.
- Text properties (SUMMARY, DESCRIPTION) escape commas, semicolons, and
  backslashes as required by §3.3.11.
- UID is deterministic per session (``<session_id>@xoxoedu``) so repeated
  exports of the same feed do not create duplicate calendar entries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple


class _SessionData(NamedTuple):
    session_id: str
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    join_url: str | None


def _escape_text(value: str) -> str:
    """Escape special characters in iCal TEXT values (RFC 5545 §3.3.11)."""
    value = value.replace("\\", "\\\\")
    value = value.replace(";", "\\;")
    value = value.replace(",", "\\,")
    value = value.replace("\n", "\\n")
    return value


def _fmt_dt(dt: datetime) -> str:
    """Format a datetime as a UTC iCal value (``YYYYMMDDTHHMMSSZ``)."""
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    """Fold a long content line at 75 octets per RFC 5545 §3.1.

    Folding inserts a CRLF followed by a single whitespace (SP) character.
    Octets are counted as UTF-8 bytes so multi-byte characters are handled
    correctly.

    RFC 5545 §3.1 allows each physical line to be at most 75 octets long
    (excluding the CRLF).  The first physical line gets 75 bytes; each
    continuation line starts with a leading SP, so its content may be at
    most 74 bytes.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line + "\r\n"

    parts: list[bytes] = []
    max_bytes = 75  # first physical line has no leading SP
    while encoded:
        chunk = encoded[:max_bytes]
        # Back off until the chunk is at a valid UTF-8 character boundary.
        while chunk:
            try:
                chunk.decode("utf-8")
                break
            except UnicodeDecodeError:
                chunk = chunk[:-1]
        if not chunk:
            break
        parts.append(chunk)
        encoded = encoded[len(chunk):]
        max_bytes = 74  # continuation lines: 1 SP + 74 bytes = 75 octets

    return ("\r\n ").join(p.decode("utf-8") for p in parts) + "\r\n"


def _prop(name: str, value: str) -> str:
    return _fold(f"{name}:{value}")


def build_ical(sessions: list[_SessionData], product_id: str = "-//XOXO Education//Calendar//EN") -> str:
    """Return a VCALENDAR string containing one VEVENT per session.

    Args:
        sessions: Ordered list of session data tuples.
        product_id: RFC 5545 PRODID property value.

    Returns:
        A UTF-8 string containing the full iCalendar document.
    """
    lines: list[str] = [
        "BEGIN:VCALENDAR\r\n",
        _prop("VERSION", "2.0"),
        _prop("PRODID", product_id),
        _prop("CALSCALE", "GREGORIAN"),
        _prop("METHOD", "PUBLISH"),
    ]

    for s in sessions:
        desc = _escape_text(s.description) if s.description else ""
        lines += [
            "BEGIN:VEVENT\r\n",
            _prop("UID", f"{s.session_id}@xoxoedu"),
            _prop("SUMMARY", _escape_text(s.title)),
            _prop("DTSTART", _fmt_dt(s.starts_at)),
            _prop("DTEND", _fmt_dt(s.ends_at)),
        ]
        if desc:
            lines.append(_prop("DESCRIPTION", desc))
        if s.join_url:
            lines.append(_prop("URL", s.join_url))
        lines.append("END:VEVENT\r\n")

    lines.append("END:VCALENDAR\r\n")
    return "".join(lines)
