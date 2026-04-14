"""Domain exception hierarchy and FastAPI exception handlers.

All application-level errors subclass ``AppException``.  Three FastAPI
exception handlers translate these (and standard HTTP / validation errors)
into the unified ``{"data": null, "error": {...}}`` response envelope.
"""

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.responses import error


class AppException(Exception):
    """Base class for all application-level exceptions.

    Subclasses override ``status_code``, ``error_code``, and ``message`` as
    class attributes.  The ``app_exception_handler`` converts instances of
    this class into the standard error envelope response.

    Attributes:
        status_code: HTTP status code to send in the response.
        error_code: Machine-readable error identifier used by API clients.
        message: Default human-readable error description.
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred"

    def __init__(self, message: str | None = None) -> None:
        """Initialise the exception with an optional custom message.

        Args:
            message: Override for the default class-level message.
                If ``None``, the class attribute value is used.
        """
        self.message = message or self.__class__.message
        super().__init__(self.message)


class EmailAlreadyRegistered(AppException):
    """Raised when a registration attempt uses an already-registered email."""

    status_code = 409
    error_code = "EMAIL_ALREADY_REGISTERED"
    message = "This email is already registered"


class InvalidCredentials(AppException):
    """Raised when email or password is incorrect during login."""

    status_code = 401
    error_code = "INVALID_CREDENTIALS"
    message = "Invalid email or password"


class EmailNotVerified(AppException):
    """Raised when a user attempts to log in before verifying their email."""

    status_code = 403
    error_code = "EMAIL_NOT_VERIFIED"
    message = "Please verify your email before logging in"


class TokenExpired(AppException):
    """Raised when a time-limited token (email or refresh) has passed its TTL."""

    status_code = 401
    error_code = "TOKEN_EXPIRED"
    message = "Token has expired"


class TokenInvalid(AppException):
    """Raised when a token fails signature verification or has an invalid format."""

    status_code = 400
    error_code = "TOKEN_INVALID"
    message = "Token is invalid"


class RefreshTokenReplayed(AppException):
    """Raised when a previously revoked refresh token is presented (replay attack).

    All active sessions for the affected user are immediately revoked.
    """

    status_code = 401
    error_code = "REFRESH_TOKEN_REPLAYED"
    message = "Refresh token reuse detected — all sessions have been revoked"


class SessionNotFound(AppException):
    """Raised when a session cannot be found by its ID."""

    status_code = 404
    error_code = "SESSION_NOT_FOUND"
    message = "Session not found"


class UserNotFound(AppException):
    """Raised when a user cannot be found by the given identifier."""

    status_code = 404
    error_code = "USER_NOT_FOUND"
    message = "User not found"


class CategoryNotFound(AppException):
    """Raised when a course creation/update references a non-existent category."""

    status_code = 422
    error_code = "CATEGORY_NOT_FOUND"
    message = "The specified category does not exist"


class CourseNotFound(AppException):
    """Raised when a course cannot be found by ID or slug."""

    status_code = 404
    error_code = "COURSE_NOT_FOUND"
    message = "Course not found"


class ChapterNotFound(AppException):
    """Raised when a chapter cannot be found by its ID."""

    status_code = 404
    error_code = "CHAPTER_NOT_FOUND"
    message = "Chapter not found"


class LessonNotFound(AppException):
    """Raised when a lesson cannot be found by its ID."""

    status_code = 404
    error_code = "LESSON_NOT_FOUND"
    message = "Lesson not found"


class SlugConflict(AppException):
    """Raised when a course slug collides with an existing one (unique violation)."""

    status_code = 409
    error_code = "SLUG_CONFLICT"
    message = "A course with this slug already exists"


class SlugImmutable(AppException):
    """Raised when a caller attempts to change the slug of a published course."""

    status_code = 409
    error_code = "SLUG_IMMUTABLE"
    message = "Slug cannot be changed after publication"


class InvalidStatusTransition(AppException):
    """Raised when a course status change violates the allowed transition graph."""

    status_code = 409
    error_code = "INVALID_STATUS_TRANSITION"
    message = "This status transition is not allowed"


class InvalidChapterIds(AppException):
    """Raised when a chapter reorder request contains IDs that don't match the course."""

    status_code = 400
    error_code = "INVALID_CHAPTER_IDS"
    message = "Provided IDs do not match the chapters in this course"


class InvalidLessonIds(AppException):
    """Raised when a lesson reorder request contains IDs that don't match the chapter."""

    status_code = 400
    error_code = "INVALID_LESSON_IDS"
    message = "Provided IDs do not match the lessons in this chapter"


class Forbidden(AppException):
    """Raised when an authenticated user lacks the required role for an operation."""

    status_code = 403
    error_code = "FORBIDDEN"
    message = "Insufficient permissions"


class AlreadyEnrolled(AppException):
    """Raised when a student attempts to enroll in a course they are already active in."""

    status_code = 409
    error_code = "ALREADY_ENROLLED"
    message = "You are already enrolled in this course"


class NotEnrolled(AppException):
    """Raised when a student accesses enrollment-gated content without an active enrollment."""

    status_code = 403
    error_code = "NOT_ENROLLED"
    message = "You must be enrolled in this course to perform this action"


class CourseNotEnrollable(AppException):
    """Raised when a student tries to enroll in a course that is not published or is not free."""

    status_code = 422
    error_code = "COURSE_NOT_ENROLLABLE"
    message = "This course is not available for enrollment"


class EnrollmentNotFound(AppException):
    """Raised when an enrollment cannot be found by its ID."""

    status_code = 404
    error_code = "ENROLLMENT_NOT_FOUND"
    message = "Enrollment not found"


class NoteNotFound(AppException):
    """Raised when a student's note on a lesson cannot be found."""

    status_code = 404
    error_code = "NOTE_NOT_FOUND"
    message = "Note not found"


class QuizNotFound(AppException):
    """Raised when a quiz cannot be found by its ID."""

    status_code = 404
    error_code = "QUIZ_NOT_FOUND"
    message = "Quiz not found"


class QuizSubmissionNotFound(AppException):
    """Raised when a quiz submission cannot be found by its ID."""

    status_code = 404
    error_code = "QUIZ_SUBMISSION_NOT_FOUND"
    message = "Quiz submission not found"


class AssignmentNotFound(AppException):
    """Raised when an assignment cannot be found by its ID."""

    status_code = 404
    error_code = "ASSIGNMENT_NOT_FOUND"
    message = "Assignment not found"


class AssignmentSubmissionNotFound(AppException):
    """Raised when an assignment submission cannot be found by its ID."""

    status_code = 404
    error_code = "ASSIGNMENT_SUBMISSION_NOT_FOUND"
    message = "Assignment submission not found"


class MaxAttemptsExceeded(AppException):
    """Raised when a student tries to submit a quiz after exhausting all attempts."""

    status_code = 409
    error_code = "MAX_ATTEMPTS_EXCEEDED"
    message = "You have used all allowed attempts for this quiz"


class UploadFailed(AppException):
    """Raised when a presigned upload URL cannot be generated."""

    status_code = 500
    error_code = "UPLOAD_FAILED"
    message = "File upload could not be initiated"


class CouponNotFound(AppException):
    """Raised when a coupon code does not match any known coupon."""

    status_code = 404
    error_code = "COUPON_NOT_FOUND"
    message = "Coupon not found"


class CouponExpired(AppException):
    """Raised when the coupon's expiry date has passed."""

    status_code = 400
    error_code = "COUPON_EXPIRED"
    message = "This coupon has expired"


class CouponUsageExceeded(AppException):
    """Raised when the coupon has reached its maximum redemption count."""

    status_code = 400
    error_code = "COUPON_USAGE_EXCEEDED"
    message = "This coupon has reached its usage limit"


class CouponNotApplicable(AppException):
    """Raised when a coupon is scoped to specific courses and the given course is not included."""

    status_code = 400
    error_code = "COUPON_NOT_APPLICABLE"
    message = "This coupon cannot be applied to the selected course"


class PaymentNotFound(AppException):
    """Raised when a payment record cannot be found."""

    status_code = 404
    error_code = "PAYMENT_NOT_FOUND"
    message = "Payment not found"


class InvalidWebhookSignature(AppException):
    """Raised when a Stripe webhook payload fails signature verification."""

    status_code = 400
    error_code = "INVALID_WEBHOOK_SIGNATURE"
    message = "Webhook signature verification failed"


class CertificateNotFound(AppException):
    """Raised when a certificate cannot be found by ID or verification token."""

    status_code = 404
    error_code = "CERTIFICATE_NOT_FOUND"
    message = "Certificate not found"


class CertificateAlreadyIssued(AppException):
    """Raised when a certificate has already been issued for this user–course pair."""

    status_code = 409
    error_code = "CERTIFICATE_ALREADY_ISSUED"
    message = "A certificate has already been issued for this course"


class NotEligibleForCertificate(AppException):
    """Raised when the student has not met the completion criteria for a certificate."""

    status_code = 422
    error_code = "NOT_ELIGIBLE_FOR_CERTIFICATE"
    message = "You have not completed all requirements to receive a certificate"


class CouponAlreadyExists(AppException):
    """Raised when a coupon creation request uses a code that already exists."""

    status_code = 409
    error_code = "COUPON_ALREADY_EXISTS"
    message = "A coupon with this code already exists"


class RefundFailed(AppException):
    """Raised when a Stripe refund cannot be processed."""

    status_code = 500
    error_code = "REFUND_FAILED"
    message = "Refund could not be processed"


class AnnouncementNotFound(AppException):
    """Raised when an announcement cannot be found by its ID."""

    status_code = 404
    error_code = "ANNOUNCEMENT_NOT_FOUND"
    message = "Announcement not found"


class SubmissionNotGradeable(AppException):
    """Raised when an admin tries to grade a submission that has not been confirmed yet."""

    status_code = 422
    error_code = "SUBMISSION_NOT_GRADEABLE"
    message = "This submission has not been confirmed by the student yet"


class SubmissionAlreadyGraded(AppException):
    """Raised when an admin tries to publish a grade that has already been published."""

    status_code = 409
    error_code = "SUBMISSION_ALREADY_GRADED"
    message = "A grade has already been published for this submission"


class AIUnavailable(AppException):
    """Raised when the LLM provider is unreachable or the circuit breaker is open."""

    status_code = 503
    error_code = "AI_UNAVAILABLE"
    message = "AI service is temporarily unavailable"


class AIQuotaExceeded(AppException):
    """Raised when a user has exhausted their monthly AI request quota."""

    status_code = 429
    error_code = "AI_QUOTA_EXCEEDED"
    message = "Monthly AI request quota exceeded"


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Convert an ``AppException`` into a JSON error envelope response.

    Args:
        request: The incoming FastAPI request (required by the handler signature).
        exc: The ``AppException`` instance to serialise.

    Returns:
        A ``JSONResponse`` with the exception's status code and error envelope.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=error(exc.error_code, exc.message),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert a FastAPI ``HTTPException`` into a JSON error envelope response.

    Args:
        request: The incoming FastAPI request.
        exc: The ``HTTPException`` to serialise.

    Returns:
        A ``JSONResponse`` with the exception's status code and error envelope.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=error("HTTP_ERROR", str(exc.detail)),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Convert a Pydantic ``RequestValidationError`` into a JSON error envelope response.

    Args:
        request: The incoming FastAPI request.
        exc: The ``RequestValidationError`` raised by Pydantic during request parsing.

    Returns:
        A 422 ``JSONResponse`` with a ``VALIDATION_ERROR`` code and serialised error details.
    """
    return JSONResponse(
        status_code=422,
        content=error("VALIDATION_ERROR", str(exc.errors())),
    )
