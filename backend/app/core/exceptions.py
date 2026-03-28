from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.responses import error


class AppException(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.__class__.message
        super().__init__(self.message)


class EmailAlreadyRegistered(AppException):
    status_code = 409
    error_code = "EMAIL_ALREADY_REGISTERED"
    message = "This email is already registered"


class InvalidCredentials(AppException):
    status_code = 401
    error_code = "INVALID_CREDENTIALS"
    message = "Invalid email or password"


class EmailNotVerified(AppException):
    status_code = 403
    error_code = "EMAIL_NOT_VERIFIED"
    message = "Please verify your email before logging in"


class TokenExpired(AppException):
    status_code = 401
    error_code = "TOKEN_EXPIRED"
    message = "Token has expired"


class TokenInvalid(AppException):
    status_code = 400
    error_code = "TOKEN_INVALID"
    message = "Token is invalid"


class RefreshTokenReplayed(AppException):
    status_code = 401
    error_code = "REFRESH_TOKEN_REPLAYED"
    message = "Refresh token reuse detected — all sessions have been revoked"


class SessionNotFound(AppException):
    status_code = 404
    error_code = "SESSION_NOT_FOUND"
    message = "Session not found"


class Forbidden(AppException):
    status_code = 403
    error_code = "FORBIDDEN"
    message = "Insufficient permissions"


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error(exc.error_code, exc.message),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error("HTTP_ERROR", str(exc.detail)),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error("VALIDATION_ERROR", str(exc.errors())),
    )
