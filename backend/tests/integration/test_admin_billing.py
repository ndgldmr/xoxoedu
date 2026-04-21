"""Integration tests for admin coupon CRUD and payment management endpoints."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.db.models.coupon import Coupon
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.payment import Payment
from app.db.models.user import User

# ── Helpers ────────────────────────────────────────────────────────────────────

async def _make_user(
    db: AsyncSession, email: str, role: str = "student"
) -> tuple[User, str]:
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("testpass"),
        role=role,
        email_verified=True,
        display_name="Test User",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, create_access_token(str(user.id), user.role)


async def _make_course(db: AsyncSession, created_by: uuid.UUID, price_cents: int = 4999) -> Course:
    course = Course(
        slug=f"course-{uuid.uuid4().hex[:8]}",
        title="Test Course",
        level="beginner",
        language="en",
        price_cents=price_cents,
        currency="USD",
        status="published",
        created_by=created_by,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _make_payment(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    status: str = "completed",
) -> Payment:
    payment = Payment(
        user_id=user_id,
        course_id=course_id,
        amount_cents=4999,
        status=status,
        provider_payment_id=f"cs_test_{uuid.uuid4().hex}",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


# ── Coupon CRUD ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_coupon(client: AsyncClient, db: AsyncSession) -> None:
    """POST /admin/coupons creates a coupon."""
    _, admin_token = await _make_user(db, f"admin-c1-{uuid.uuid4().hex[:6]}@test.com", "admin")

    resp = await client.post(
        "/api/v1/admin/coupons",
        json={
            "code": f"TEST{uuid.uuid4().hex[:6].upper()}",
            "discount_type": "percentage",
            "discount_value": 20.0,
            "max_uses": 100,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["discount_type"] == "percentage"
    assert data["discount_value"] == 20.0
    assert data["uses_count"] == 0


@pytest.mark.asyncio
async def test_create_coupon_student_forbidden(client: AsyncClient, db: AsyncSession) -> None:
    """Students cannot create coupons."""
    _, student_token = await _make_user(db, f"stu-c1-{uuid.uuid4().hex[:6]}@test.com")

    resp = await client.post(
        "/api/v1/admin/coupons",
        json={"code": "NOPE", "discount_type": "fixed", "discount_value": 500},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_coupon_duplicate_code(client: AsyncClient, db: AsyncSession) -> None:
    """Creating a coupon with a duplicate code returns 409."""
    _, admin_token = await _make_user(db, f"admin-c2-{uuid.uuid4().hex[:6]}@test.com", "admin")
    code = f"DUP{uuid.uuid4().hex[:6].upper()}"
    db.add(Coupon(
        code=code,
        discount_type="fixed",
        discount_value=500,
        uses_count=0,
    ))
    await db.commit()

    resp = await client.post(
        "/api/v1/admin/coupons",
        json={"code": code, "discount_type": "fixed", "discount_value": 500},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_coupons(client: AsyncClient, db: AsyncSession) -> None:
    """GET /admin/coupons returns paginated coupon list."""
    _, admin_token = await _make_user(db, f"admin-c3-{uuid.uuid4().hex[:6]}@test.com", "admin")
    db.add(Coupon(
        code=f"LIST{uuid.uuid4().hex[:6].upper()}",
        discount_type="percentage",
        discount_value=10.0,
        uses_count=0,
    ))
    await db.commit()

    resp = await client.get(
        "/api/v1/admin/coupons",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 1
    assert len(body["data"]) >= 1


@pytest.mark.asyncio
async def test_update_coupon(client: AsyncClient, db: AsyncSession) -> None:
    """PATCH /admin/coupons/{id} updates expiry and max_uses."""
    _, admin_token = await _make_user(db, f"admin-c4-{uuid.uuid4().hex[:6]}@test.com", "admin")
    coupon = Coupon(
        code=f"UPD{uuid.uuid4().hex[:6].upper()}",
        discount_type="fixed",
        discount_value=1000.0,
        uses_count=0,
    )
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)

    new_expiry = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    resp = await client.patch(
        f"/api/v1/admin/coupons/{coupon.id}",
        json={"expires_at": new_expiry, "max_uses": 50},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["max_uses"] == 50


@pytest.mark.asyncio
async def test_delete_coupon(client: AsyncClient, db: AsyncSession) -> None:
    """DELETE /admin/coupons/{id} removes the coupon."""
    _, admin_token = await _make_user(db, f"admin-c5-{uuid.uuid4().hex[:6]}@test.com", "admin")
    coupon = Coupon(
        code=f"DEL{uuid.uuid4().hex[:6].upper()}",
        discount_type="percentage",
        discount_value=5.0,
        uses_count=0,
    )
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)

    resp = await client.delete(
        f"/api/v1/admin/coupons/{coupon.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204

    deleted = await db.get(Coupon, coupon.id)
    assert deleted is None


# ── Admin Payments ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_admin_payments_all_students(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/payments returns payments across all students."""
    admin, admin_token = await _make_user(db, f"admin-p1-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student1, _ = await _make_user(db, f"stu-p1a-{uuid.uuid4().hex[:6]}@test.com")
    student2, _ = await _make_user(db, f"stu-p1b-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    await _make_payment(db, student1.id, course.id)
    await _make_payment(db, student2.id, course.id)

    resp = await client.get(
        "/api/v1/admin/payments",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 2


@pytest.mark.asyncio
async def test_list_admin_payments_filter_by_status(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/payments?status=pending filters correctly."""
    admin, admin_token = await _make_user(db, f"admin-p2-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, _ = await _make_user(db, f"stu-p2-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    await _make_payment(db, student.id, course.id, status="pending")

    resp = await client.get(
        "/api/v1/admin/payments?status=pending",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert all(p["status"] == "pending" for p in data)


@pytest.mark.asyncio
async def test_list_admin_payments_filter_by_course(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /admin/payments?course_id=... filters to that course only."""
    admin, admin_token = await _make_user(db, f"admin-p3-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, _ = await _make_user(db, f"stu-p3-{uuid.uuid4().hex[:6]}@test.com")
    course_a = await _make_course(db, admin.id)
    course_b = await _make_course(db, admin.id)
    await _make_payment(db, student.id, course_a.id)
    await _make_payment(db, student.id, course_b.id)

    resp = await client.get(
        f"/api/v1/admin/payments?course_id={course_a.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert all(p["course_id"] == str(course_a.id) for p in data)


@pytest.mark.asyncio
async def test_refund_payment(client: AsyncClient, db: AsyncSession) -> None:
    """POST /admin/payments/{id}/refund triggers Stripe refund and updates statuses."""
    admin, admin_token = await _make_user(db, f"admin-r1-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, _ = await _make_user(db, f"stu-r1-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    payment = await _make_payment(db, student.id, course.id, status="completed")
    enrollment = Enrollment(user_id=student.id, course_id=course.id, status="active")
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)

    mock_session = MagicMock()
    mock_session.payment_intent = "pi_test_123"
    mock_refund = MagicMock()
    mock_refund.id = "re_test_abc"

    with patch("app.modules.admin.service.stripe.StripeClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.checkout.sessions.retrieve.return_value = mock_session
        mock_client.refunds.create.return_value = mock_refund

        resp = await client.post(
            f"/api/v1/admin/payments/{payment.id}/refund",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "refunded"
    assert data["stripe_refund_id"] == "re_test_abc"

    await db.refresh(payment)
    await db.refresh(enrollment)
    assert payment.status == "refunded"
    assert enrollment.status == "refunded"


@pytest.mark.asyncio
async def test_refund_already_refunded_payment(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /admin/payments/{id}/refund on a non-completed payment returns 500."""
    admin, admin_token = await _make_user(db, f"admin-r2-{uuid.uuid4().hex[:6]}@test.com", "admin")
    student, _ = await _make_user(db, f"stu-r2-{uuid.uuid4().hex[:6]}@test.com")
    course = await _make_course(db, admin.id)
    payment = await _make_payment(db, student.id, course.id, status="refunded")

    resp = await client.post(
        f"/api/v1/admin/payments/{payment.id}/refund",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 500
