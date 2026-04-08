"""Pydantic schemas for certificates."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CertificateOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    verification_token: str
    issued_at: datetime
    pdf_url: str | None

    model_config = {"from_attributes": True}


class CertificateRequestOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    status: str
    requested_at: datetime

    model_config = {"from_attributes": True}


class VerifyResponse(BaseModel):
    verification_token: str
    student_name: str
    course_title: str
    issued_at: datetime
    instructor_name: str | None
    pdf_url: str | None
