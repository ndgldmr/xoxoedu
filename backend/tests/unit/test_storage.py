"""Unit tests for the Cloudflare R2 storage utility helpers."""

from unittest.mock import patch

from app.core.storage import get_public_url


def test_get_public_url_with_custom_domain() -> None:
    """Uses the custom R2_PUBLIC_URL when configured."""
    with patch("app.core.storage.settings") as mock_settings:
        mock_settings.R2_PUBLIC_URL = "https://assets.xoxoedu.com"
        mock_settings.R2_ACCOUNT_ID = "abc123"
        mock_settings.R2_BUCKET = "xoxoedu-uploads"
        url = get_public_url("assignments/uuid/file.pdf")
    assert url == "https://assets.xoxoedu.com/assignments/uuid/file.pdf"


def test_get_public_url_default_endpoint() -> None:
    """Falls back to the standard R2 endpoint URL when no custom domain is set."""
    with patch("app.core.storage.settings") as mock_settings:
        mock_settings.R2_PUBLIC_URL = ""
        mock_settings.R2_ACCOUNT_ID = "abc123"
        mock_settings.R2_BUCKET = "xoxoedu-uploads"
        url = get_public_url("assignments/uuid/file.pdf")
    assert url == (
        "https://abc123.r2.cloudflarestorage.com"
        "/xoxoedu-uploads/assignments/uuid/file.pdf"
    )


def test_get_public_url_strips_trailing_slash() -> None:
    """Trailing slash on R2_PUBLIC_URL does not produce a double slash."""
    with patch("app.core.storage.settings") as mock_settings:
        mock_settings.R2_PUBLIC_URL = "https://assets.xoxoedu.com/"
        mock_settings.R2_ACCOUNT_ID = "abc123"
        mock_settings.R2_BUCKET = "xoxoedu-uploads"
        url = get_public_url("file.pdf")
    assert url == "https://assets.xoxoedu.com/file.pdf"
