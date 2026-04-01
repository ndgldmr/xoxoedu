"""Pure-ASGI request-ID and structured-logging middleware."""

import logging
import time
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("xoxoedu")


class RequestIDMiddleware:
    """Pure ASGI middleware that attaches a request ID and emits structured logs.

    Implemented as a raw ASGI callable rather than Starlette's
    ``BaseHTTPMiddleware`` to avoid the anyio task-group overhead that
    ``BaseHTTPMiddleware`` introduces for every request.

    Each HTTP/WebSocket request receives a UUID4 ``x-request-id`` response
    header. A structured log entry is emitted when the response status line is
    sent, capturing path, method, status code, and wall-clock duration.

    Attributes:
        app: The downstream ASGI application.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialise the middleware with the next ASGI app in the stack.

        Args:
            app: The downstream ASGI application to wrap.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle an ASGI connection by injecting request-ID tracking.

        Non-HTTP scopes (e.g. ``lifespan``) are passed through unchanged.

        Args:
            scope: ASGI connection scope mapping.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope["state"] = getattr(scope.get("state"), "__dict__", {})
        start = time.perf_counter()

        async def send_with_header(message: dict) -> None:
            """Intercept ``http.response.start`` to inject the request-ID header and log.

            Args:
                message: ASGI message dict forwarded from the downstream app.
            """
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
