"""Business logic for admin user, coupon, payment, grading, analytics, and announcements."""

import uuid
from datetime import UTC, datetime, timedelta

import stripe
from sqlalchemy import case, delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import (
    AssignmentSubmissionNotFound,
    CourseNotFound,
    CouponAlreadyExists,
    CouponNotFound,
    PaymentNotFound,
    RefundFailed,
    SubmissionAlreadyGraded,
    SubmissionNotGradeable,
    UserNotFound,
)
from app.db.models.announcement import Announcement
from app.db.models.assignment import Assignment, AssignmentSubmission
from app.db.models.coupon import Coupon
from app.db.models.course import Chapter, Course, Lesson
from app.db.models.enrollment import Enrollment, LessonProgress
from app.db.models.payment import Payment
from app.db.models.quiz import Quiz, QuizSubmission
from app.db.models.user import User
from app.modules.admin.tasks import send_announcement_emails
from app.modules.admin.schemas import (
    AdminPaymentOut,
    AdminSubmissionOut,
    AnnouncementIn,
    AnnouncementOut,
    CourseAnalyticsOut,
    CouponCreateIn,
    CouponUpdateIn,
    GradeSubmissionIn,
    LessonDropOffItem,
    PlatformAnalyticsOut,
    RefundOut,
    StudentProgressRow,
    TopCourseItem,
)


async def list_users(db: AsyncSession, skip: int, limit: int) -> tuple[list[User], int]:
    """Return a paginated list of all users with the total count.

    Args:
        db: Async database session.
        skip: Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(users, total)`` where ``total`` is the unfiltered row count.
    """
    count_result = await db.execute(select(User))
    total = len(count_result.scalars().all())

    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total


async def update_role(db: AsyncSession, user_id: uuid.UUID, role: str) -> User:
    """Change the role of a user by ID.

    Args:
        db: Async database session.
        user_id: UUID of the user to update.
        role: The new role string (e.g. ``"admin"``, ``"instructor"``, ``"student"``).

    Returns:
        The updated ``User`` ORM instance.

    Raises:
        UserNotFound: If no user with that ID exists.
    """
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Hard-delete a user record by ID.

    Args:
        db: Async database session.
        user_id: UUID of the user to delete.

    Raises:
        UserNotFound: If no user with that ID exists.
    """
    user = await db.get(User, user_id)
    if not user:
        raise UserNotFound()
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()


# ── Coupons ────────────────────────────────────────────────────────────────────

async def create_coupon(db: AsyncSession, data: CouponCreateIn) -> Coupon:
    """Create a new discount coupon.

    Args:
        db: Async database session.
        data: Validated coupon creation payload.

    Returns:
        The created ``Coupon`` ORM instance.

    Raises:
        CouponAlreadyExists: If a coupon with the same code already exists.
    """
    existing = await db.scalar(select(Coupon).where(Coupon.code == data.code))
    if existing:
        raise CouponAlreadyExists()

    coupon = Coupon(
        code=data.code,
        discount_type=data.discount_type,
        discount_value=data.discount_value,
        max_uses=data.max_uses,
        applies_to=[str(cid) for cid in data.applies_to] if data.applies_to else None,
        expires_at=data.expires_at,
    )
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return coupon


async def list_coupons(
    db: AsyncSession, skip: int, limit: int
) -> tuple[list[Coupon], int]:
    """Return a paginated list of all coupons, newest first.

    Args:
        db: Async database session.
        skip: Number of rows to skip.
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(coupons, total)``.
    """
    from sqlalchemy import func
    base = select(Coupon)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.order_by(Coupon.created_at.desc()).offset(skip).limit(limit)
    )
    return list(rows.all()), total or 0


async def update_coupon(
    db: AsyncSession, coupon_id: uuid.UUID, data: CouponUpdateIn
) -> Coupon:
    """Update a coupon's expiry date and/or usage cap.

    Args:
        db: Async database session.
        coupon_id: UUID of the coupon to update.
        data: Fields to update.

    Returns:
        The updated ``Coupon`` ORM instance.

    Raises:
        CouponNotFound: If no coupon with that ID exists.
    """
    coupon = await db.get(Coupon, coupon_id)
    if not coupon:
        raise CouponNotFound()
    coupon.expires_at = data.expires_at
    coupon.max_uses = data.max_uses
    await db.commit()
    await db.refresh(coupon)
    return coupon


async def delete_coupon(db: AsyncSession, coupon_id: uuid.UUID) -> None:
    """Hard-delete a coupon by ID.

    Args:
        db: Async database session.
        coupon_id: UUID of the coupon to delete.

    Raises:
        CouponNotFound: If no coupon with that ID exists.
    """
    coupon = await db.get(Coupon, coupon_id)
    if not coupon:
        raise CouponNotFound()
    await db.delete(coupon)
    await db.commit()


# ── Payments ───────────────────────────────────────────────────────────────────

async def list_payments_admin(
    db: AsyncSession,
    course_id: uuid.UUID | None,
    status: str | None,
    skip: int,
    limit: int,
) -> tuple[list[AdminPaymentOut], int]:
    """Return a paginated, filterable list of all payments across the platform.

    Args:
        db: Async database session.
        course_id: Optional filter by course.
        status: Optional filter by payment status.
        skip: Number of rows to skip.
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(payments, total)``.
    """
    from sqlalchemy import func
    base = select(Payment)
    if course_id:
        base = base.where(Payment.course_id == course_id)
    if status:
        base = base.where(Payment.status == status)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.options(selectinload(Payment.user), selectinload(Payment.course))
        .order_by(Payment.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    results: list[AdminPaymentOut] = []
    for p in rows:
        out = AdminPaymentOut.model_validate(p)
        out.user_email = p.user.email if p.user else None
        out.course_title = p.course.title if p.course else None
        results.append(out)
    return results, total or 0


async def refund_payment(db: AsyncSession, payment_id: uuid.UUID) -> RefundOut:
    """Trigger a Stripe refund for a completed payment.

    Retrieves the Stripe Checkout Session to resolve the payment intent, then
    creates a refund via the Stripe API.  Updates the ``Payment`` and any active
    ``Enrollment`` to ``"refunded"`` status on success.

    Args:
        db: Async database session.
        payment_id: UUID of the payment to refund.

    Returns:
        A ``RefundOut`` with the Stripe refund ID.

    Raises:
        PaymentNotFound: If no payment with that ID exists.
        RefundFailed: If the payment is not in ``"completed"`` state, or if the
            Stripe API call fails.
    """
    payment = await db.scalar(
        select(Payment)
        .where(Payment.id == payment_id)
        .options(selectinload(Payment.user), selectinload(Payment.course))
    )
    if not payment:
        raise PaymentNotFound()

    if payment.status != "completed":
        raise RefundFailed(f"Cannot refund a payment with status '{payment.status}'")

    try:
        client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)
        session = client.checkout.sessions.retrieve(payment.provider_payment_id)
        payment_intent_id = session.payment_intent
        refund = client.refunds.create(params={"payment_intent": payment_intent_id})
    except stripe.StripeError as exc:
        raise RefundFailed() from exc

    payment.status = "refunded"
    await db.flush()

    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == payment.user_id,
            Enrollment.course_id == payment.course_id,
            Enrollment.status == "active",
        )
    )
    if enrollment:
        enrollment.status = "refunded"

    await db.commit()
    return RefundOut(
        payment_id=payment.id,
        status="refunded",
        stripe_refund_id=refund.id,
    )


# ── Grading ────────────────────────────────────────────────────────────────────

async def list_submissions(
    db: AsyncSession,
    course_id: uuid.UUID,
    status_filter: str | None,
    skip: int,
    limit: int,
) -> tuple[list[AdminSubmissionOut], int]:
    """Return a paginated submission queue for all assignments in a course.

    Args:
        db: Async database session.
        course_id: UUID of the course whose submissions to list.
        status_filter: Optional filter — ``"ungraded"``, ``"graded"``, or ``"flagged"``.
        skip: Number of rows to skip.
        limit: Maximum rows to return.

    Returns:
        A tuple of ``(submissions, total)``.
    """
    base = (
        select(AssignmentSubmission)
        .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
        .join(Lesson, Lesson.id == Assignment.lesson_id)
        .join(Chapter, Chapter.id == Lesson.chapter_id)
        .where(Chapter.course_id == course_id)
        .where(AssignmentSubmission.submitted_at.is_not(None))
    )

    if status_filter == "ungraded":
        base = base.where(AssignmentSubmission.grade_published_at.is_(None))
    elif status_filter == "graded":
        base = base.where(AssignmentSubmission.grade_published_at.is_not(None))
    elif status_filter == "flagged":
        base = base.where(AssignmentSubmission.scan_status == "infected")

    total_q = select(func.count()).select_from(base.subquery())
    total = await db.scalar(total_q) or 0

    rows = await db.scalars(
        base.options(selectinload(AssignmentSubmission.user))
        .order_by(AssignmentSubmission.submitted_at.asc())
        .offset(skip)
        .limit(limit)
    )

    results: list[AdminSubmissionOut] = []
    for s in rows:
        out = AdminSubmissionOut.model_validate(s)
        out.user_email = s.user.email if s.user else None
        results.append(out)
    return results, total


async def grade_submission(
    db: AsyncSession,
    submission_id: uuid.UUID,
    grader_id: uuid.UUID,
    data: GradeSubmissionIn,
) -> AdminSubmissionOut:
    """Save a grade (draft or published) on an assignment submission.

    Args:
        db: Async database session.
        submission_id: UUID of the submission to grade.
        grader_id: UUID of the admin performing the grading.
        data: Grade payload including score, feedback, and publish flag.

    Returns:
        The updated ``AdminSubmissionOut``.

    Raises:
        AssignmentSubmissionNotFound: If no submission with that ID exists.
        SubmissionNotGradeable: If ``submitted_at`` is ``None`` (upload not confirmed).
        SubmissionAlreadyGraded: If ``publish=True`` but a grade is already published.
    """
    submission = await db.scalar(
        select(AssignmentSubmission)
        .where(AssignmentSubmission.id == submission_id)
        .options(selectinload(AssignmentSubmission.user))
    )
    if not submission:
        raise AssignmentSubmissionNotFound()
    if submission.submitted_at is None:
        raise SubmissionNotGradeable()
    if data.publish and submission.grade_published_at is not None:
        raise SubmissionAlreadyGraded()

    submission.grade_score = data.grade_score
    submission.grade_feedback = data.grade_feedback
    submission.graded_by = grader_id
    if data.publish:
        submission.grade_published_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(submission)

    out = AdminSubmissionOut.model_validate(submission)
    out.user_email = submission.user.email if submission.user else None
    return out


async def reopen_submission(
    db: AsyncSession, submission_id: uuid.UUID
) -> AdminSubmissionOut:
    """Allow a student to upload a new attempt by marking the submission as reopened.

    Args:
        db: Async database session.
        submission_id: UUID of the submission to reopen.

    Returns:
        The updated ``AdminSubmissionOut``.

    Raises:
        AssignmentSubmissionNotFound: If no submission with that ID exists.
    """
    submission = await db.scalar(
        select(AssignmentSubmission)
        .where(AssignmentSubmission.id == submission_id)
        .options(selectinload(AssignmentSubmission.user))
    )
    if not submission:
        raise AssignmentSubmissionNotFound()

    submission.is_reopened = True
    await db.commit()
    await db.refresh(submission)

    out = AdminSubmissionOut.model_validate(submission)
    out.user_email = submission.user.email if submission.user else None
    return out


# ── Analytics ──────────────────────────────────────────────────────────────────

async def get_course_analytics(
    db: AsyncSession, course_id: uuid.UUID
) -> CourseAnalyticsOut:
    """Compute aggregated analytics for a single course.

    Args:
        db: Async database session.
        course_id: UUID of the course to analyse.

    Returns:
        A ``CourseAnalyticsOut`` with enrollment counts, quiz scores, and lesson drop-off.

    Raises:
        CourseNotFound: If no course with that ID exists.
    """
    course = await db.get(Course, course_id)
    if not course:
        raise CourseNotFound()

    # ── enrollment counts ──────────────────────────────────────────────────────
    enroll_rows = await db.execute(
        select(Enrollment.status, func.count(Enrollment.id).label("cnt"))
        .where(Enrollment.course_id == course_id)
        .group_by(Enrollment.status)
    )
    status_counts: dict[str, int] = {row.status: row.cnt for row in enroll_rows}
    total_enrollments = sum(status_counts.values())
    active_enrollments = status_counts.get("active", 0)
    completed_enrollments = status_counts.get("completed", 0)
    completion_rate = (
        completed_enrollments / total_enrollments if total_enrollments > 0 else 0.0
    )

    # ── average quiz score ─────────────────────────────────────────────────────
    avg_score_row = await db.scalar(
        select(
            func.avg(
                case(
                    (QuizSubmission.max_score > 0,
                     QuizSubmission.score * 100.0 / QuizSubmission.max_score),
                    else_=None,
                )
            )
        )
        .select_from(QuizSubmission)
        .join(Quiz, Quiz.id == QuizSubmission.quiz_id)
        .join(Lesson, Lesson.id == Quiz.lesson_id)
        .join(Chapter, Chapter.id == Lesson.chapter_id)
        .where(Chapter.course_id == course_id)
    )
    average_quiz_score = float(avg_score_row) if avg_score_row is not None else None

    # ── lesson drop-off ────────────────────────────────────────────────────────
    lessons_q = await db.execute(
        select(Lesson.id, Lesson.title, Chapter.title.label("chapter_title"))
        .join(Chapter, Chapter.id == Lesson.chapter_id)
        .where(Chapter.course_id == course_id)
        .order_by(Chapter.position, Lesson.position)
    )
    lesson_rows = lessons_q.all()

    drop_off: list[LessonDropOffItem] = []
    active_total = max(active_enrollments + completed_enrollments, 1)
    for row in lesson_rows:
        completion_count = await db.scalar(
            select(func.count(distinct(LessonProgress.user_id)))
            .where(
                LessonProgress.lesson_id == row.id,
                LessonProgress.status == "completed",
            )
        ) or 0
        drop_off.append(
            LessonDropOffItem(
                lesson_id=row.id,
                lesson_title=row.title,
                chapter_title=row.chapter_title,
                completion_count=completion_count,
                completion_rate=completion_count / active_total,
            )
        )

    return CourseAnalyticsOut(
        course_id=course_id,
        total_enrollments=total_enrollments,
        active_enrollments=active_enrollments,
        completed_enrollments=completed_enrollments,
        completion_rate=completion_rate,
        average_quiz_score=average_quiz_score,
        lesson_drop_off=drop_off,
    )


async def get_course_students(
    db: AsyncSession,
    course_id: uuid.UUID,
    skip: int,
    limit: int,
) -> tuple[list[StudentProgressRow], int]:
    """Return a paginated progress table of all students enrolled in a course.

    Args:
        db: Async database session.
        course_id: UUID of the course.
        skip: Number of rows to skip.
        limit: Maximum rows to return.

    Returns:
        A tuple of ``(student_rows, total)``.
    """
    # Total lesson count for the course (denominator for completion_pct)
    total_lessons = await db.scalar(
        select(func.count(Lesson.id))
        .join(Chapter, Chapter.id == Lesson.chapter_id)
        .where(Chapter.course_id == course_id)
    ) or 0

    base = select(Enrollment).where(Enrollment.course_id == course_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0

    enrollments = await db.scalars(
        base.options(
            selectinload(Enrollment.user).selectinload(User.profile)
        )
        .order_by(Enrollment.enrolled_at.desc())
        .offset(skip)
        .limit(limit)
    )

    rows: list[StudentProgressRow] = []
    for enrollment in enrollments:
        user = enrollment.user

        completed_lessons = await db.scalar(
            select(func.count(LessonProgress.id))
            .join(Lesson, Lesson.id == LessonProgress.lesson_id)
            .join(Chapter, Chapter.id == Lesson.chapter_id)
            .where(
                Chapter.course_id == course_id,
                LessonProgress.user_id == user.id,
                LessonProgress.status == "completed",
            )
        ) or 0

        last_active_at = await db.scalar(
            select(func.max(LessonProgress.updated_at))
            .join(Lesson, Lesson.id == LessonProgress.lesson_id)
            .join(Chapter, Chapter.id == Lesson.chapter_id)
            .where(
                Chapter.course_id == course_id,
                LessonProgress.user_id == user.id,
            )
        )

        completion_pct = (
            completed_lessons / total_lessons if total_lessons > 0 else 0.0
        )
        profile = user.profile if user.profile else None

        rows.append(
            StudentProgressRow(
                user_id=user.id,
                user_email=user.email,
                display_name=profile.display_name if profile else None,
                enrolled_at=enrollment.enrolled_at,
                status=enrollment.status,
                completion_pct=completion_pct,
                last_active_at=last_active_at,
            )
        )

    return rows, total


async def get_platform_analytics(db: AsyncSession) -> PlatformAnalyticsOut:
    """Compute platform-wide aggregate metrics.

    Args:
        db: Async database session.

    Returns:
        A ``PlatformAnalyticsOut`` with totals for students, enrollments, revenue,
        and the top 5 courses by enrollment count.
    """
    total_students = await db.scalar(
        select(func.count(User.id)).where(User.role == "student")
    ) or 0

    cutoff = datetime.now(UTC) - timedelta(days=30)
    active_students_30d = await db.scalar(
        select(func.count(distinct(LessonProgress.user_id))).where(
            LessonProgress.updated_at >= cutoff
        )
    ) or 0

    total_enrollments = await db.scalar(select(func.count(Enrollment.id))) or 0

    total_revenue_cents = await db.scalar(
        select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
            Payment.status == "completed"
        )
    ) or 0

    top_course_rows = await db.execute(
        select(
            Enrollment.course_id,
            Course.title,
            func.count(Enrollment.id).label("enrollment_count"),
        )
        .join(Course, Course.id == Enrollment.course_id)
        .group_by(Enrollment.course_id, Course.title)
        .order_by(func.count(Enrollment.id).desc())
        .limit(5)
    )
    top_courses = [
        TopCourseItem(
            course_id=row.course_id,
            title=row.title,
            enrollment_count=row.enrollment_count,
        )
        for row in top_course_rows
    ]

    return PlatformAnalyticsOut(
        total_students=total_students,
        active_students_30d=active_students_30d,
        total_enrollments=total_enrollments,
        total_revenue_cents=total_revenue_cents,
        top_courses=top_courses,
    )


# ── Announcements ──────────────────────────────────────────────────────────────

async def create_announcement(
    db: AsyncSession,
    admin_id: uuid.UUID,
    data: AnnouncementIn,
) -> AnnouncementOut:
    """Create an announcement and dispatch email notifications to targeted students.

    For ``scope="course"`` the email is sent to all actively enrolled students in
    that course.  For ``scope="platform"`` the email is sent to all student-role
    users.  The Celery task is enqueued synchronously; ``sent_at`` is stamped after
    the task is dispatched (not after delivery).

    Args:
        db: Async database session.
        admin_id: UUID of the admin creating the announcement.
        data: Validated announcement payload.

    Returns:
        The created ``AnnouncementOut``.

    Raises:
        CourseNotFound: If ``scope="course"`` but ``course_id`` is not provided or
            the referenced course does not exist.
    """
    from app.core.exceptions import AppException

    if data.scope == "course":
        if not data.course_id:
            raise AppException("course_id is required when scope is 'course'")
        course = await db.get(Course, data.course_id)
        if not course:
            raise CourseNotFound()

    announcement = Announcement(
        title=data.title,
        body=data.body,
        scope=data.scope,
        course_id=data.course_id,
        created_by=admin_id,
    )
    db.add(announcement)
    await db.flush()

    # Collect recipient emails
    if data.scope == "course":
        email_rows = await db.scalars(
            select(User.email)
            .join(Enrollment, Enrollment.user_id == User.id)
            .where(
                Enrollment.course_id == data.course_id,
                Enrollment.status == "active",
            )
        )
    else:
        email_rows = await db.scalars(
            select(User.email).where(User.role == "student")
        )

    recipient_emails = list(email_rows.all())

    # Enqueue Celery task
    send_announcement_emails.delay(
        str(announcement.id),
        recipient_emails,
        data.title,
        data.body,
    )

    announcement.sent_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(announcement)
    return AnnouncementOut.model_validate(announcement)


async def list_announcements(
    db: AsyncSession, skip: int, limit: int
) -> tuple[list[AnnouncementOut], int]:
    """Return a paginated list of announcements, newest first.

    Args:
        db: Async database session.
        skip: Number of rows to skip.
        limit: Maximum rows to return.

    Returns:
        A tuple of ``(announcements, total)``.
    """
    base = select(Announcement)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = await db.scalars(
        base.order_by(Announcement.created_at.desc()).offset(skip).limit(limit)
    )
    return [AnnouncementOut.model_validate(a) for a in rows.all()], total
