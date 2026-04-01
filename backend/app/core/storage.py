"""Cloudflare R2 (S3-compatible) client and presigned URL helpers.

The boto3 client is initialised lazily on first use and cached as a
module-level singleton.  Tests can override ``get_r2_client`` via
``monkeypatch`` without touching environment variables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    import boto3 as boto3_type  # noqa: F401 — type-check only

_r2_client: object | None = None  # module-level lazy singleton


def get_r2_client() -> object:
    """Return the module-level R2 boto3 client, creating it on first call.

    The endpoint URL is derived from ``settings.R2_ACCOUNT_ID``.  All
    requests are signed with SigV4.

    Returns:
        A ``botocore.client.S3`` instance configured for Cloudflare R2.
    """
    global _r2_client
    if _r2_client is None:
        import boto3
        from botocore.config import Config

        endpoint = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        _r2_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _r2_client


def generate_presigned_put(key: str, content_type: str, expires_in: int = 300) -> str:
    """Return a presigned PUT URL for uploading a file directly to R2.

    The client should HTTP PUT the file bytes to this URL.  No backend
    proxy is involved — the upload goes straight from the browser to R2.

    Args:
        key: The R2 object key (path within the bucket).
        content_type: MIME type of the file being uploaded.
        expires_in: URL validity in seconds (default 300 = 5 minutes).

    Returns:
        A presigned URL string the client can PUT to.
    """
    client = get_r2_client()
    return client.generate_presigned_url(  # type: ignore[union-attr]
        "put_object",
        Params={
            "Bucket": settings.R2_BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def get_public_url(key: str) -> str:
    """Return the public URL for a stored object.

    Uses ``settings.R2_PUBLIC_URL`` when a custom domain is configured,
    otherwise falls back to the standard R2 endpoint URL.

    Args:
        key: The R2 object key (path within the bucket).

    Returns:
        A fully-qualified public URL for the object.
    """
    if settings.R2_PUBLIC_URL:
        return f"{settings.R2_PUBLIC_URL.rstrip('/')}/{key}"
    return (
        f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        f"/{settings.R2_BUCKET}/{key}"
    )
