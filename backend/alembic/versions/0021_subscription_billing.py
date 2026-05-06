"""AL-BE-3: Subscription billing — add stripe_customer_id and seed launch plans.

Adds the ``stripe_customer_id`` column to ``subscriptions`` (nullable, unique)
so that each student maps to exactly one Stripe Customer for life.

Seeds the three launch ``SubscriptionPlan`` rows using hard-coded UUIDs so
the migration is idempotent (``ON CONFLICT DO NOTHING``).

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# ── revision identifiers ────────────────────────────────────────────────────
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Hard-coded UUIDs ensure the seed INSERT is idempotent across environments.
_PLAN_ID_BR = "a1b2c3d4-0001-4000-8000-000000000001"
_PLAN_ID_CA = "a1b2c3d4-0002-4000-8000-000000000002"
_PLAN_ID_EU = "a1b2c3d4-0003-4000-8000-000000000003"


def upgrade() -> None:
    # ── 1. Add stripe_customer_id to subscriptions ──────────────────────────
    op.add_column(
        "subscriptions",
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_subscriptions_stripe_customer_id",
        "subscriptions",
        ["stripe_customer_id"],
    )
    op.create_index(
        "ix_subscriptions_stripe_customer_id",
        "subscriptions",
        ["stripe_customer_id"],
    )

    # ── 2. Seed the three launch subscription plans ──────────────────────────
    op.execute(
        f"""
        INSERT INTO subscription_plans
            (id, name, market, currency, amount_cents, interval, is_active,
             created_at, updated_at)
        VALUES
            ('{_PLAN_ID_BR}', 'Brazil Monthly',  'BR', 'BRL', 1000, 'month', true, now(), now()),
            ('{_PLAN_ID_CA}', 'Canada Monthly',  'CA', 'CAD', 1000, 'month', true, now(), now()),
            ('{_PLAN_ID_EU}', 'Europe Monthly',  'EU', 'EUR', 1499, 'month', true, now(), now())
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # Remove seed rows by their hard-coded UUIDs.
    op.execute(
        f"""
        DELETE FROM subscription_plans
        WHERE id IN ('{_PLAN_ID_BR}', '{_PLAN_ID_CA}', '{_PLAN_ID_EU}')
        """
    )

    op.drop_index("ix_subscriptions_stripe_customer_id", table_name="subscriptions")
    op.drop_constraint(
        "uq_subscriptions_stripe_customer_id", "subscriptions", type_="unique"
    )
    op.drop_column("subscriptions", "stripe_customer_id")
