"""Pydantic schemas for the RAG course assistant endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AssistantRequest(BaseModel):
    """Request body for the course assistant endpoint.

    Attributes:
        question: The student's question, 1–2000 characters.
    """

    question: str = Field(..., min_length=1, max_length=2000)


class MessageOut(BaseModel):
    """A single message turn returned to the client.

    Attributes:
        id: UUID of the ``ConversationMessage`` row.
        role: ``"user"`` or ``"assistant"``.
        content: Full text of the turn.
        created_at: Server timestamp of message creation.
    """

    id: uuid.UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AssistantResponse(BaseModel):
    """Response body for a successful assistant query.

    Attributes:
        conversation_id: The UUID of the conversation (created or continued).
        message: The assistant's reply as a ``MessageOut``.
        retrieved_lesson_ids: Deduplicated list of lesson UUIDs whose chunks
            were retrieved by the vector search and contributed to the answer.
    """

    conversation_id: uuid.UUID
    message: MessageOut
    retrieved_lesson_ids: list[uuid.UUID]


class CitationOut(BaseModel):
    """A single source citation returned at the end of a streamed response.

    Attributes:
        lesson_id: UUID of the lesson the chunk was drawn from.
        lesson_title: Display title of the lesson, for client rendering.
        source: Origin of the chunk — ``"content"`` or ``"transcript"``.
    """

    lesson_id: uuid.UUID
    lesson_title: str
    source: str


class ConversationOut(BaseModel):
    """Summary of a conversation for the list endpoint.

    Attributes:
        id: UUID of the conversation.
        course_id: The course this conversation is scoped to.
        created_at: When the conversation was first started.
        updated_at: When it was last updated.
        last_message: The most recent message, or ``None`` if no messages yet.
    """

    id: uuid.UUID
    course_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    last_message: MessageOut | None
