"""Thin wrapper around the Mux Video API.

Provides two functions needed by Sprint 8A:
- ``create_upload`` — create a direct upload and return the upload URL + asset ID.
- ``get_audio_url`` — return the audio download URL for a ready asset (used by
  the Whisper transcription task).

Mux API docs: https://docs.mux.com/api-reference
"""

from __future__ import annotations

import httpx

from app.config import settings

_MUX_API_BASE = "https://api.mux.com"


def _auth() -> tuple[str, str]:
    return (settings.MUX_TOKEN_ID, settings.MUX_TOKEN_SECRET)


async def create_upload(cors_origin: str = "*") -> tuple[str, str]:
    """Create a Mux direct upload and return ``(upload_url, upload_id)``.

    The caller should redirect the client to PUT the video file directly to
    ``upload_url``.  ``upload_id`` should be persisted on the lesson row
    (``lesson.video_asset_id``) temporarily so the ``video.upload.asset_created``
    webhook handler can correlate the upload back to the lesson and replace it
    with the real Mux asset ID.

    Args:
        cors_origin: Allowed CORS origin for the presigned upload URL.
            Defaults to ``"*"`` for development; set to your frontend URL in
            production.

    Returns:
        A ``(upload_url, upload_id)`` tuple.

    Raises:
        httpx.HTTPStatusError: When Mux returns a non-2xx response.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{_MUX_API_BASE}/video/v1/uploads",
            auth=_auth(),
            json={
                "cors_origin": cors_origin,
                "new_asset_settings": {
                    "playback_policy": ["public"],
                    "mp4_support": "capped-1080p",
                },
            },
            timeout=10,
        )
    response.raise_for_status()
    data = response.json()["data"]
    upload_url: str = data["url"]
    upload_id: str = data["id"]  # asset_id is not available until upload completes
    return upload_url, upload_id


def get_hls_url(playback_id: str) -> str:
    """Return the HLS stream URL for a Mux asset.

    This URL works on all Mux plans including free.  The transcription task
    uses ffmpeg to extract audio from the stream into a temporary file before
    sending it to Whisper.

    Args:
        playback_id: The Mux playback ID stored on the lesson row.

    Returns:
        A URL string pointing to the HLS manifest.
    """
    return f"https://stream.mux.com/{playback_id}.m3u8"
