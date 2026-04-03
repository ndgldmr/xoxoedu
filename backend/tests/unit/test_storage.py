"""Unit tests for the Cloudflare R2 storage utility helpers."""

from unittest.mock import MagicMock, patch

import app.core.storage as storage_module
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


def test_get_r2_client_uses_explicit_endpoint_url() -> None:
    """R2_ENDPOINT_URL overrides the account-ID-derived endpoint (e.g. for MinIO)."""
    storage_module._r2_client = None  # reset singleton
    with (
        patch("app.core.storage.settings") as mock_settings,
        patch("boto3.client", return_value=MagicMock()) as mock_boto,
    ):
        mock_settings.R2_ENDPOINT_URL = "http://localhost:9000"
        mock_settings.R2_ACCOUNT_ID = "unused"
        mock_settings.R2_ACCESS_KEY_ID = "minioadmin"
        mock_settings.R2_SECRET_ACCESS_KEY = "minioadmin"
        storage_module.get_r2_client()

    _, kwargs = mock_boto.call_args
    assert kwargs["endpoint_url"] == "http://localhost:9000"
    storage_module._r2_client = None  # clean up


def test_get_r2_client_derives_endpoint_from_account_id() -> None:
    """When R2_ENDPOINT_URL is blank, the endpoint is derived from R2_ACCOUNT_ID."""
    storage_module._r2_client = None  # reset singleton
    with (
        patch("app.core.storage.settings") as mock_settings,
        patch("boto3.client", return_value=MagicMock()) as mock_boto,
    ):
        mock_settings.R2_ENDPOINT_URL = ""
        mock_settings.R2_ACCOUNT_ID = "abc123"
        mock_settings.R2_ACCESS_KEY_ID = "key"
        mock_settings.R2_SECRET_ACCESS_KEY = "secret"
        storage_module.get_r2_client()

    _, kwargs = mock_boto.call_args
    assert kwargs["endpoint_url"] == "https://abc123.r2.cloudflarestorage.com"
    storage_module._r2_client = None  # clean up
