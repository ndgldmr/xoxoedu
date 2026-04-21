"""Helpers for normalizing and generating stable mentionable usernames."""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_USERNAME_LEN = 50
_USERNAME_RE = re.compile(r"[^a-z0-9_]+")
_UNDERSCORE_RE = re.compile(r"_+")


def normalize_username_candidate(value: str | None) -> str:
    """Normalize free-form text into a lowercase ``username`` candidate."""
    candidate = (value or "").strip().lower()
    candidate = _USERNAME_RE.sub("_", candidate)
    candidate = _UNDERSCORE_RE.sub("_", candidate).strip("_")
    return candidate or "user"


def build_default_username(email: str | None, display_name: str | None = None) -> str:
    """Return a deterministic username fallback for direct ORM inserts."""
    source = display_name or (email.split("@", 1)[0] if email else None)
    base = normalize_username_candidate(source)
    suffix_seed = (email or display_name or "user").encode()
    suffix = hashlib.sha1(suffix_seed).hexdigest()[:6]
    max_base_len = _MAX_USERNAME_LEN - len(suffix) - 1
    return f"{base[:max_base_len]}_{suffix}"


async def generate_unique_username(
    db: AsyncSession,
    *,
    email: str,
    display_name: str | None = None,
) -> str:
    """Generate a human-readable username and avoid collisions in the DB."""
    from app.db.models.user import User

    base = normalize_username_candidate(display_name or email.split("@", 1)[0])
    candidate = base[:_MAX_USERNAME_LEN]
    suffix = 2

    while await db.scalar(select(User.id).where(User.username == candidate)) is not None:
        suffix_text = str(suffix)
        max_base_len = _MAX_USERNAME_LEN - len(suffix_text) - 1
        candidate = f"{base[:max_base_len]}_{suffix_text}"
        suffix += 1

    return candidate
