import logging
import time
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("xoxoedu")


class RequestIDMiddleware:
    """Pure ASGI middleware — avoids BaseHTTPMiddleware's anyio task-spawning issues."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope["state"] = getattr(scope.get("state"), "__dict__", {})
        start = time.perf_counter()

        async def send_with_header(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                logger.info(
                    "request",
                    extra={
                        "request_id": request_id,
                        "path": scope.get("path", ""),
                        "method": scope.get("method", ""),
                        "status_code": message.get("status", 0),
                        "duration_ms": duration_ms,
                    },
                )
            await send(message)

        await self.app(scope, receive, send_with_header)
