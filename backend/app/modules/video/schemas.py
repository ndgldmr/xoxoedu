"""Pydantic schemas for video and transcript endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class VideoUploadResponseOut(BaseModel):
    """Response returned when an admin requests a Mux video upload URL.

    Attributes:
        upload_url: Presigned PUT URL; the client uploads the video file directly here.
        asset_id: Mux asset ID; persisted on the lesson row for webhook correlation.
    """

    upload_url: str
    asset_id: str


class TranscriptOut(BaseModel):
    """Serialised lesson transcript returned to clients.

    Attributes:
        lesson_id: UUID of the lesson this transcript belongs to.
        vtt_url: Public URL of the WebVTT caption file stored in R2.
        plain_text: Full transcript as plain text.
        updated_at: Timestamp of the most recent update (auto-generated or admin edit).
    """

    lesson_id: uuid.UUID
    vtt_url: str
    plain_text: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class TranscriptUpdateIn(BaseModel):
    """Admin payload for editing a lesson transcript.

    Attributes:
        plain_text: The corrected transcript text; replaces the existing value.
    """

    plain_text: str = Field(min_length=1)
