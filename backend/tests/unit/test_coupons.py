"""Unit tests for pure coupon discount calculation and validation logic."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.modules.coupons.service import _calculate_discount


# ── _calculate_discount ────────────────────────────────────────────────────────

def _coupon(discount_type: str, discount_value: float) -> SimpleNamespace:
    return SimpleNamespace(discount_type=discount_type, discount_value=discount_value)


def test_percentage_discount_basic() -> None:
    """20% off a $100 course = $20 discount."""
    coupon = _coupon("percentage", 20.0)
    assert _calculate_discount(coupon, 10000) == 2000


def test_percentage_discount_rounds_down() -> None:
    """Fractional cent is truncated (int conversion)."""
    coupon = _coupon("percentage", 33.3)
    assert _calculate_discount(coupon, 1000) == 333


def test_percentage_100_gives_full_discount() -> None:
    coupon = _coupon("percentage", 100.0)
    assert _calculate_discount(coupon, 5000) == 5000


def test_fixed_discount_basic() -> None:
    """$10 fixed discount off a $50 course = $10 discount."""
    coupon = _coupon("fixed", 1000.0)
    assert _calculate_discount(coupon, 5000) == 1000


def test_fixed_discount_capped_at_original_price() -> None:
    """Fixed discount cannot exceed the original price."""
    coupon = _coupon("fixed", 9999.0)
    assert _calculate_discount(coupon, 500) == 500


def test_percentage_discount_capped_at_original_price() -> None:
    """Percentage > 100 is clamped to the full original amount."""
    coupon = _coupon("percentage", 150.0)
    assert _calculate_discount(coupon, 1000) == 1000


def test_zero_discount() -> None:
    coupon = _coupon("percentage", 0.0)
    assert _calculate_discount(coupon, 5000) == 0


# ── validate_coupon (async, uses mocked DB) ────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_coupon_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """An expired coupon raises CouponExpired."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.core.exceptions import CouponExpired
    from app.modules.coupons import service

    expired_coupon = SimpleNamespace(
        id=uuid.uuid4(),
        code="OLD10",
        discount_type="percentage",
        discount_value=10.0,
        max_uses=None,
        uses_count=0,
        applies_to=None,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=expired_coupon)

    with pytest.raises(CouponExpired):
        await service.validate_coupon(db, "OLD10", uuid.uuid4(), 5000)


@pytest.mark.asyncio
async def test_validate_coupon_usage_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A coupon at its max_uses raises CouponUsageExceeded."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.core.exceptions import CouponUsageExceeded
    from app.modules.coupons import service

    exhausted = SimpleNamespace(
        id=uuid.uuid4(),
        code="USED",
        discount_type="fixed",
        discount_value=500.0,
        max_uses=5,
        uses_count=5,
        applies_to=None,
        expires_at=None,
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=exhausted)

    with pytest.raises(CouponUsageExceeded):
        await service.validate_coupon(db, "USED", uuid.uuid4(), 5000)


@pytest.mark.asyncio
async def test_validate_coupon_not_applicable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scoped coupon used on the wrong course raises CouponNotApplicable."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.core.exceptions import CouponNotApplicable
    from app.modules.coupons import service

    other_course_id = str(uuid.uuid4())
    scoped = SimpleNamespace(
        id=uuid.uuid4(),
        code="SCOPED",
        discount_type="percentage",
        discount_value=15.0,
        max_uses=None,
        uses_count=0,
        applies_to=[other_course_id],
        expires_at=None,
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=scoped)

    with pytest.raises(CouponNotApplicable):
        await service.validate_coupon(db, "SCOPED", uuid.uuid4(), 5000)


@pytest.mark.asyncio
async def test_validate_coupon_global_applies_to_any_course() -> None:
    """A global coupon (applies_to=None) validates for any course."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.modules.coupons import service

    global_coupon = SimpleNamespace(
        id=uuid.uuid4(),
        code="GLOBAL",
        discount_type="percentage",
        discount_value=10.0,
        max_uses=None,
        uses_count=0,
        applies_to=None,
        expires_at=None,
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=global_coupon)

    result = await service.validate_coupon(db, "GLOBAL", uuid.uuid4(), 10000)
    assert result.valid is True
    assert result.discount_amount_cents == 1000
    assert result.final_amount_cents == 9000
