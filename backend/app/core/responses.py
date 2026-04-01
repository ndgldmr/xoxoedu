"""Envelope-builder helpers that standardise all JSON API responses."""

from typing import Any


def ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a successful response envelope.

    Args:
        data: The primary payload — any JSON-serialisable value.
        meta: Optional pagination or supplementary metadata.

    Returns:
        A dict of the form ``{"data": ..., "meta": {...}, "error": None}``.
    """
    return {"data": data, "meta": meta or {}, "error": None}


def error(code: str, message: str) -> dict[str, Any]:
    """Build an error response envelope.

    Args:
        code: Machine-readable error code (e.g. ``"COURSE_NOT_FOUND"``).
        message: Human-readable description of the error.

    Returns:
        A dict of the form ``{"data": None, "meta": {}, "error": {"code": ..., "message": ...}}``.
    """
    return {"data": None, "meta": {}, "error": {"code": code, "message": message}}
