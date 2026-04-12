"""Chat endpoint request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Incoming chat message from the user."""

    message: str = Field(..., min_length=1, max_length=8000, description="User's question")
    session_id: str = Field(
        default="",
        description="Session ID for conversation continuity. A new ID is created if empty.",
    )
    stream: bool = Field(default=False, description="If True, use streaming SSE response")


class ChatResponse(BaseModel):
    """Non-streaming chat response."""

    answer: str = Field(..., description="The assistant's answer")
    session_id: str = Field(..., description="Session ID (use in subsequent requests)")


class StreamEvent(BaseModel):
    """A single server-sent event in a streaming response."""

    event: str = Field(..., description="Event type: 'chunk', 'done', or 'error'")
    data: str = Field(..., description="Event payload")
    session_id: str = Field(default="")
