"""Rename notification_prefs to notification_preferences.

Aligns the physical table name with the ORM model class name
(NotificationPreference) and the broader naming convention used by the
aligned domain tables.  The unique constraint and any downstream references
are updated in the same migration.

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-29

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("notification_prefs", "notification_preferences")
    op.execute(
        "ALTER TABLE notification_preferences "
        "RENAME CONSTRAINT uq_notification_prefs_user_type "
        "TO uq_notification_preferences_user_type"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE notification_preferences "
        "RENAME CONSTRAINT uq_notification_preferences_user_type "
        "TO uq_notification_prefs_user_type"
    )
    op.rename_table("notification_preferences", "notification_prefs")
