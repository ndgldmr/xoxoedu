"""Pydantic schemas for assignments and file submissions."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── Admin input schemas ────────────────────────────────────────────────────────

class AssignmentIn(BaseModel):
    """Payload for creating an assignment on a lesson.

    Attributes:
        lesson_id: The lesson this assignment is attached to.
        title: Short display name for the assignment.
        instructions: Full assignment brief (may contain Markdown).
        max_file_size_bytes: Upload size limit in bytes (default 10 MiB).
        allowed_extensions: Permitted file extensions without leading dots,
            e.g. ``["pdf", "docx", "zip"]``.
    """

    lesson_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    instructions: str = Field(min_length=1)
    max_file_size_bytes: int = Field(default=10_485_760, ge=1)
    allowed_extensions: list[str] = Field(default_factory=list)


class AssignmentOut(BaseModel):
    """Full assignment representation returned to clients.

    Attributes:
        id: Assignment UUID.
        lesson_id: Parent lesson UUID.
        title: Display name.
        instructions: Assignment brief.
        max_file_size_bytes: Upload size limit in bytes.
        allowed_extensions: Permitted file extensions.
        created_at: Row creation timestamp.
    """

    id: uuid.UUID
    lesson_id: uuid.UUID
    title: str
    instructions: str
    max_file_size_bytes: int
    allowed_extensions: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Upload flow schemas ────────────────────────────────────────────────────────

class UploadRequestIn(BaseModel):
    """Student's request for a presigned upload URL.

    Attributes:
        file_name: Original filename (used as the final segment of the R2 key).
        mime_type: MIME type of the file being uploaded.
        file_size: File size in bytes; validated against ``max_file_size_bytes``.
    """

    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size: int = Field(ge=1)


class UploadResponseOut(BaseModel):
    """Response containing the presigned PUT URL for a direct R2 upload.

    Attributes:
        submission_id: UUID of the newly created ``AssignmentSubmission`` row.
        upload_url: Presigned PUT URL; valid for ``expires_in`` seconds.
        expires_at: Absolute expiry timestamp for the presigned URL.
    """

    submission_id: uuid.UUID
    upload_url: str
    expires_at: datetime


# ── Submission output schema ───────────────────────────────────────────────────

class SubmissionOut(BaseModel):
    """Serialised assignment submission returned to clients.

    Attributes:
        id: Submission UUID.
        assignment_id: The assignment this submission belongs to.
        user_id: The student who submitted.
        file_name: Original filename.
        file_size: Declared file size in bytes.
        mime_type: Declared MIME type.
        scan_status: Virus scan state (``"pending"``, ``"clean"``, or ``"infected"``).
        submitted_at: Set when the student confirms the upload is complete.
        created_at: Row creation timestamp.
    """

    id: uuid.UUID
    assignment_id: uuid.UUID
    user_id: uuid.UUID
    file_name: str
    file_size: int
    mime_type: str
    scan_status: str
    submitted_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
