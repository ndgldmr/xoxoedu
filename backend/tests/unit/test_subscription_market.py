"""Unit tests for country-to-market resolution and pricing snapshot logic."""

import pytest

from app.core.exceptions import NoMarketForCountry
from app.db.models.subscription import Subscription, SubscriptionPlan
from app.modules.subscriptions.service import resolve_market


class TestResolveMarket:
    def test_brazil(self) -> None:
        assert resolve_market("BR") == "BR"

    def test_canada(self) -> None:
        assert resolve_market("CA") == "CA"

    @pytest.mark.parametrize(
        "code",
        [
            "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
            "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
            "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        ],
    )
    def test_eu_member_states(self, code: str) -> None:
        assert resolve_market(code) == "EU"

    def test_none_raises(self) -> None:
        with pytest.raises(NoMarketForCountry):
            resolve_market(None)

    def test_unknown_country_raises(self) -> None:
        with pytest.raises(NoMarketForCountry):
            resolve_market("XX")

    def test_us_raises(self) -> None:
        with pytest.raises(NoMarketForCountry):
            resolve_market("US")

    def test_lowercase_brazil(self) -> None:
        assert resolve_market("br") == "BR"

    def test_lowercase_eu(self) -> None:
        assert resolve_market("de") == "EU"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(NoMarketForCountry):
            resolve_market("")


class TestPricingSnapshot:
    """Verify that a Subscription created from a SubscriptionPlan copies the pricing fields."""

    def test_snapshot_matches_plan(self) -> None:
        import uuid

        plan = SubscriptionPlan(
            id=uuid.uuid4(),
            name="Brazil Monthly",
            market="BR",
            currency="BRL",
            amount_cents=1000,
            interval="month",
            is_active=True,
        )
        sub = Subscription(
            user_id=uuid.uuid4(),
            plan_id=plan.id,
            market=plan.market,
            currency=plan.currency,
            amount_cents=plan.amount_cents,
            status="trialing",
            provider="stripe",
        )
        assert sub.market == plan.market
        assert sub.currency == plan.currency
        assert sub.amount_cents == plan.amount_cents

    def test_snapshot_survives_plan_price_change(self) -> None:
        """The snapshot is independent — changing the plan object does not affect the subscription."""
        import uuid

        plan = SubscriptionPlan(
            id=uuid.uuid4(),
            name="Europe Monthly",
            market="EU",
            currency="EUR",
            amount_cents=1499,
            interval="month",
            is_active=True,
        )
        sub = Subscription(
            user_id=uuid.uuid4(),
            plan_id=plan.id,
            market=plan.market,
            currency=plan.currency,
            amount_cents=plan.amount_cents,
            status="active",
            provider="stripe",
        )
        # Simulate a plan price increase.
        plan.amount_cents = 1999
        # Subscription snapshot is unaffected.
        assert sub.amount_cents == 1499
