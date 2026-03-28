from typing import Any


def ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"data": data, "meta": meta or {}, "error": None}


def error(code: str, message: str) -> dict[str, Any]:
    return {"data": None, "meta": {}, "error": {"code": code, "message": message}}
