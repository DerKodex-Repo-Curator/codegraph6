"""Indexing endpoint schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class IndexRequest(BaseModel):
    """Request to start a repository indexing job."""

    repository_url: str = Field(
        default="https://github.com/tiangolo/fastapi",
        description="Git repository URL to index",
    )
    force: bool = Field(
        default=False,
        description="Force re-indexing even if commit SHA matches",
    )


class IndexResponse(BaseModel):
    """Response after starting an indexing job."""

    job_id: str = Field(..., description="Job ID for status polling")
    status: str = Field(..., description="Initial job status")
    message: str = Field(default="Indexing started in the background")


class IndexStatusResponse(BaseModel):
    """Current status of an indexing job."""

    job_id: str
    status: str
    progress_pct: float = 0.0
    processed_files: int = 0
    total_files: int = 0
    error_message: str = ""
