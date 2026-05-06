"""Pydantic schemas for attendance request and response shapes."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AttendanceIn(BaseModel):
    """Request body for marking or updating attendance for a live session.

    Attributes:
        status: The attendance status to record.
        user_id: Target student UUID.  Admins may supply any batch member's
            UUID; students must omit this field (or supply their own UUID).
            When omitted the endpoint defaults to the authenticated caller.
    """

    status: Literal["present", "absent", "late"]
    user_id: uuid.UUID | None = None


class AttendanceOut(BaseModel):
    """Single attendance record returned to clients."""

    id: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionSummaryOut(BaseModel):
    """Per-session attendance totals within a batch report.

    Attributes:
        session_id: UUID of the live session.
        title: Session title.
        starts_at: UTC start datetime.
        present: Count of members marked present.
        absent: Count of members marked absent.
        late: Count of members marked late.
        unmarked: Members with no attendance record for this session.
        total_members: Total batch member count.
        attendance_rate: ``(present + late) / total_members``.
            Indicates what fraction of the cohort showed up.
    """

    session_id: uuid.UUID
    title: str
    starts_at: datetime
    present: int
    absent: int
    late: int
    unmarked: int
    total_members: int
    attendance_rate: float


class StudentSummaryOut(BaseModel):
    """Per-student attendance breakdown within a batch report.

    Attributes:
        user_id: UUID of the student.
        email: Student email address.
        display_name: Student display name (may be ``None``).
        attendance: Mapping of ``session_id`` → attendance status for sessions
            where a record exists.  Sessions with no record are absent from
            this dict.
        present_count: Number of sessions where the student was marked present.
        absent_count: Number of sessions where the student was marked absent.
        late_count: Number of sessions where the student was marked late.
        attendance_rate: ``(present_count + late_count) / total_sessions``.
    """

    user_id: uuid.UUID
    email: str
    display_name: str | None
    attendance: dict[str, str]
    present_count: int
    absent_count: int
    late_count: int
    attendance_rate: float


class BatchAttendanceReportOut(BaseModel):
    """Full batch attendance report returned to admins.

    Attributes:
        batch_id: UUID of the queried batch.
        total_sessions: Number of sessions included in the report.
        total_members: Number of students included in the report.
        overall_attendance_rate: ``(total present + late records) /
            (total_sessions * total_members)``.  Zero when either dimension
            is empty.
        session_summaries: Per-session aggregate totals, ordered by
            ``starts_at`` ascending.
        student_summaries: Per-student breakdowns, ordered by email ascending.
    """

    batch_id: uuid.UUID
    total_sessions: int
    total_members: int
    overall_attendance_rate: float
    session_summaries: list[SessionSummaryOut]
    student_summaries: list[StudentSummaryOut]
