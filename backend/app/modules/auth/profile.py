"""Shared auth/profile constants and helpers for aligned onboarding."""

from __future__ import annotations

from typing import Protocol


SUPPORTED_SIGNUP_COUNTRIES: tuple[tuple[str, str], ...] = (
    ("AT", "Austria"),
    ("BE", "Belgium"),
    ("BG", "Bulgaria"),
    ("BR", "Brazil"),
    ("CA", "Canada"),
    ("CY", "Cyprus"),
    ("CZ", "Czech Republic"),
    ("DE", "Germany"),
    ("DK", "Denmark"),
    ("EE", "Estonia"),
    ("ES", "Spain"),
    ("FI", "Finland"),
    ("FR", "France"),
    ("GR", "Greece"),
    ("HR", "Croatia"),
    ("HU", "Hungary"),
    ("IE", "Ireland"),
    ("IT", "Italy"),
    ("LT", "Lithuania"),
    ("LU", "Luxembourg"),
    ("LV", "Latvia"),
    ("MT", "Malta"),
    ("NL", "Netherlands"),
    ("PL", "Poland"),
    ("PT", "Portugal"),
    ("RO", "Romania"),
    ("SE", "Sweden"),
    ("SI", "Slovenia"),
    ("SK", "Slovakia"),
)
SUPPORTED_SIGNUP_COUNTRY_CODES: tuple[str, ...] = tuple(code for code, _ in SUPPORTED_SIGNUP_COUNTRIES)
SUPPORTED_COUNTRY_NAMES_BY_CODE: dict[str, str] = dict(SUPPORTED_SIGNUP_COUNTRIES)

SUPPORTED_GENDERS: tuple[str, ...] = (
    "male",
    "female",
    "other",
    "prefer_not_to_say",
)

SUPPORTED_SOCIAL_LINK_KEYS: tuple[str, ...] = (
    "linkedin",
    "instagram",
    "tiktok",
    "website",
)

ALLOWED_AVATAR_MIME_TYPES: tuple[str, ...] = (
    "image/jpeg",
    "image/png",
    "image/webp",
)
AVATAR_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024


class ProfileFields(Protocol):
    """Structural fields required for profile-complete checks."""

    avatar_url: str | None
    country: str | None
    date_of_birth: object | None
    gender: str | None
    gender_self_describe: str | None


def is_profile_complete(profile: ProfileFields) -> bool:
    """Return whether the profile contains all required WC-03 onboarding data."""
    if not profile.avatar_url or not profile.country or not profile.date_of_birth or not profile.gender:
        return False

    return True
