"""AL-BE-3 fix: drop unique constraint on subscriptions.stripe_customer_id.

A student who cancels and resubscribes creates a second Subscription row but
reuses the same Stripe Customer ID.  The UNIQUE constraint erroneously blocks
this, so it is replaced with a plain index (lookups still fast, duplicates
allowed).

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_subscriptions_stripe_customer_id", "subscriptions", type_="unique"
    )
    # The index created in 0021 is retained — no need to recreate it.


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_subscriptions_stripe_customer_id",
        "subscriptions",
        ["stripe_customer_id"],
    )
