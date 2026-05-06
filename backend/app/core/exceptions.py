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


class UsernameAlreadyTaken(AppException):
    """Raised when a registration attempt uses an already-claimed username."""

    status_code = 409
    error_code = "USERNAME_ALREADY_TAKEN"
    message = "This username is already taken"


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

    status_code = 401
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


class ResourceNotFound(AppException):
    """Raised when a lesson resource cannot be found by its ID."""

    status_code = 404
    error_code = "RESOURCE_NOT_FOUND"
    message = "Resource not found"


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


class ConversationNotFound(AppException):
    """Raised when a conversation cannot be found by ID."""

    status_code = 404
    error_code = "CONVERSATION_NOT_FOUND"
    message = "Conversation not found"


class AssistantRateLimited(AppException):
    """Raised when a student exceeds the per-hour query limit on the course assistant."""

    status_code = 429
    error_code = "ASSISTANT_RATE_LIMITED"
    message = "Rate limit exceeded: 20 assistant queries per hour per course"


class DiscussionPostNotFound(AppException):
    """Raised when a discussion post cannot be found by its ID."""

    status_code = 404
    error_code = "DISCUSSION_POST_NOT_FOUND"
    message = "Discussion post not found"


class DiscussionPostForbidden(AppException):
    """Raised when a user attempts an operation they are not authorised to perform on a post."""

    status_code = 403
    error_code = "DISCUSSION_POST_FORBIDDEN"
    message = "You do not have permission to perform this action on this post"


class CannotVoteOnOwnPost(AppException):
    """Raised when a user attempts to upvote their own discussion post."""

    status_code = 403
    error_code = "CANNOT_VOTE_ON_OWN_POST"
    message = "You cannot upvote your own post"


class CannotFlagOwnPost(AppException):
    """Raised when a user attempts to flag their own discussion post."""

    status_code = 403
    error_code = "CANNOT_FLAG_OWN_POST"
    message = "You cannot flag your own post"


class DiscussionFlagNotFound(AppException):
    """Raised when a moderation flag cannot be found by its ID."""

    status_code = 404
    error_code = "DISCUSSION_FLAG_NOT_FOUND"
    message = "Moderation flag not found"


class DiscussionFlagAlreadyResolved(AppException):
    """Raised when an admin attempts to resolve a flag that is no longer open."""

    status_code = 409
    error_code = "DISCUSSION_FLAG_ALREADY_RESOLVED"
    message = "This flag has already been resolved"


class ProgramNotFound(AppException):
    """Raised when a program cannot be found by its ID."""

    status_code = 404
    error_code = "PROGRAM_NOT_FOUND"
    message = "Program not found"


class ProgramEnrollmentRequired(AppException):
    """Raised when a batch operation requires an active program enrollment that is missing."""

    status_code = 409
    error_code = "PROGRAM_ENROLLMENT_REQUIRED"
    message = "Student must have an active program enrollment before joining a batch"


class BatchNotFound(AppException):
    """Raised when a batch cannot be found by its ID."""

    status_code = 404
    error_code = "BATCH_NOT_FOUND"
    message = "Batch not found"


class BatchEnrollmentNotFound(AppException):
    """Raised when a batch enrollment cannot be found for the given user."""

    status_code = 404
    error_code = "BATCH_ENROLLMENT_NOT_FOUND"
    message = "Batch membership not found"


class BatchAtCapacity(AppException):
    """Raised when adding a member would exceed the batch's seat limit."""

    status_code = 409
    error_code = "BATCH_AT_CAPACITY"
    message = "This batch has reached its maximum capacity"


class BatchArchived(AppException):
    """Raised when a write operation targets an archived batch."""

    status_code = 409
    error_code = "BATCH_ARCHIVED"
    message = "Archived batches do not accept changes"


class AlreadyInBatch(AppException):
    """Raised when a student is already a member of the given batch."""

    status_code = 409
    error_code = "ALREADY_IN_BATCH"
    message = "This student is already a member of the batch"


class StudentAlreadyInActiveBatch(AppException):
    """Raised when a student already belongs to an active batch for the same program."""

    status_code = 409
    error_code = "STUDENT_ALREADY_IN_ACTIVE_BATCH"
    message = "This student is already in an active batch for this program"


class StudentAlreadyInProgramBatch(AppException):
    """Raised when a student has already selected any batch for their active program."""

    status_code = 409
    error_code = "STUDENT_ALREADY_IN_PROGRAM_BATCH"
    message = "You have already selected a batch for this program"


class BatchProgramMismatch(AppException):
    """Raised when a student selects a batch outside their active program."""

    status_code = 409
    error_code = "BATCH_PROGRAM_MISMATCH"
    message = "You can only select batches from your active program"


class BatchNotOpenForEnrollment(AppException):
    """Raised when a batch is not currently open for student self-selection."""

    status_code = 409
    error_code = "BATCH_NOT_OPEN_FOR_ENROLLMENT"
    message = "This batch is not open for enrollment"


class BatchTransferCurrentBatchRequired(AppException):
    """Raised when a student must already belong to a batch to request a transfer."""

    status_code = 409
    error_code = "BATCH_TRANSFER_CURRENT_BATCH_REQUIRED"
    message = "You must already belong to a batch before requesting a transfer"


class BatchTransferSameBatch(AppException):
    """Raised when a transfer target matches the student's current batch."""

    status_code = 409
    error_code = "BATCH_TRANSFER_SAME_BATCH"
    message = "You are already in the requested batch"


class BatchTransferRequestAlreadyPending(AppException):
    """Raised when a student already has a pending transfer request."""

    status_code = 409
    error_code = "BATCH_TRANSFER_REQUEST_ALREADY_PENDING"
    message = "You already have a pending batch transfer request"


class BatchTransferRequestNotFound(AppException):
    """Raised when a batch transfer request cannot be found."""

    status_code = 404
    error_code = "BATCH_TRANSFER_REQUEST_NOT_FOUND"
    message = "Batch transfer request not found"


class BatchTransferRequestAlreadyResolved(AppException):
    """Raised when an admin acts on a non-pending batch transfer request."""

    status_code = 409
    error_code = "BATCH_TRANSFER_REQUEST_ALREADY_RESOLVED"
    message = "This batch transfer request has already been resolved"


class BatchTransferProgramMismatch(AppException):
    """Raised when a transfer target falls outside the student's active program."""

    status_code = 409
    error_code = "BATCH_TRANSFER_PROGRAM_MISMATCH"
    message = "You can only transfer into batches from your active program"


class LiveSessionNotFound(AppException):
    """Raised when a live session cannot be found by its ID."""

    status_code = 404
    error_code = "LIVE_SESSION_NOT_FOUND"
    message = "Live session not found"


class LiveSessionCanceled(AppException):
    """Raised when a write operation targets a canceled live session."""

    status_code = 409
    error_code = "LIVE_SESSION_CANCELED"
    message = "Canceled sessions cannot be modified"


class NotABatchMember(AppException):
    """Raised when attendance is marked for a user who is not in the session's batch."""

    status_code = 403
    error_code = "NOT_A_BATCH_MEMBER"
    message = "The specified user is not a member of this batch"


class AttendanceNotFound(AppException):
    """Raised when an attendance record cannot be found."""

    status_code = 404
    error_code = "ATTENDANCE_NOT_FOUND"
    message = "Attendance record not found"


class ProgramStepNotFound(AppException):
    """Raised when a program step cannot be found by its ID."""

    status_code = 404
    error_code = "PROGRAM_STEP_NOT_FOUND"
    message = "Program step not found"


class ProgramStepConflict(AppException):
    """Raised when a step with the same position or course already exists in the program."""

    status_code = 409
    error_code = "PROGRAM_STEP_CONFLICT"
    message = "A step with this position or course already exists in this program"


class ProgramEnrollmentNotFound(AppException):
    """Raised when a program enrollment cannot be found by its ID."""

    status_code = 404
    error_code = "PROGRAM_ENROLLMENT_NOT_FOUND"
    message = "Program enrollment not found"


class DuplicateActiveProgramEnrollment(AppException):
    """Raised when a student already has an active program enrollment."""

    status_code = 409
    error_code = "DUPLICATE_ACTIVE_PROGRAM_ENROLLMENT"
    message = "Student already has an active program enrollment"


class SubscriptionRequired(AppException):
    """Raised when content access is attempted without an active subscription."""

    status_code = 402
    error_code = "SUBSCRIPTION_REQUIRED"
    message = "An active subscription is required to access this content"


class SubscriptionNotFound(AppException):
    """Raised when a subscription cannot be found by its ID."""

    status_code = 404
    error_code = "SUBSCRIPTION_NOT_FOUND"
    message = "Subscription not found"


class NoMarketForCountry(AppException):
    """Raised when a student's country does not map to any launch market."""

    status_code = 422
    error_code = "NO_MARKET_FOR_COUNTRY"
    message = "No subscription plan is available for your country"


class PlacementResultNotFound(AppException):
    """Raised when a placement result cannot be found by its ID."""

    status_code = 404
    error_code = "PLACEMENT_RESULT_NOT_FOUND"
    message = "Placement result not found"


class NoPlacementResult(AppException):
    """Raised when a student requests their placement result before completing the assessment."""

    status_code = 404
    error_code = "NO_PLACEMENT_RESULT"
    message = "No placement result found for this student"


class LessonLocked(AppException):
    """Raised when a student attempts to save progress on a lesson not yet accessible.

    Covers both admin hard-locks (``Lesson.is_locked == True``) and sequential
    position locks (preceding lesson not yet completed).
    """

    status_code = 403
    error_code = "LESSON_LOCKED"
    message = "This lesson is not yet accessible"


class ProgramNotActive(AppException):
    """Raised when a student requests program progress but has no active program enrollment."""

    status_code = 403
    error_code = "PROGRAM_NOT_ACTIVE"
    message = "You do not have an active program enrollment"


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
