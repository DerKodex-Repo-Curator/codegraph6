"""Domain models shared across all agents.

These Pydantic models represent the core entities in the knowledge graph and
the conversation layer. They are intentionally kept as plain data containers —
no business logic lives here.
"""

from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Graph entity models
# ---------------------------------------------------------------------------


class NodeKind(StrEnum):
    """Labels that can appear on Neo4j nodes."""

    REPOSITORY = "Repository"
    FILE = "File"
    MODULE = "Module"
    CLASS = "Class"
    FUNCTION = "Function"
    ROUTE = "Route"
    SCHEMA = "Schema"
    DEPENDENCY = "Dependency"
    IMPORT = "Import"


class RepositoryNode(BaseModel):
    """Represents the root Repository node in the knowledge graph."""

    url: str
    name: str
    commit_sha: str
    indexed_at: datetime = Field(default_factory=datetime.utcnow)


class FileNode(BaseModel):
    """Represents a single Python source file."""

    path: str  # repo-relative path, e.g. "fastapi/routing.py"
    module_path: str  # "fastapi.routing"
    loc: int = 0
    language: str = "python"


class ClassNode(BaseModel):
    """Represents a Python class definition."""

    qualified_name: str  # "fastapi.routing.APIRouter"
    name: str
    bases: list[str] = Field(default_factory=list)
    is_abstract: bool = False
    docstring: str = ""
    start_line: int = 0
    end_line: int = 0


class FunctionNode(BaseModel):
    """Represents a Python function or method."""

    qualified_name: str
    name: str
    is_async: bool = False
    is_method: bool = False
    decorators: list[str] = Field(default_factory=list)
    signature: str = ""
    docstring: str = ""
    source: str = ""
    start_line: int = 0
    end_line: int = 0


class RouteNode(FunctionNode):
    """A FastAPI route handler — extends FunctionNode with HTTP metadata."""

    http_method: str = ""
    path: str = ""
    response_model: str = ""
    status_code: int = 200
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Conversation models
# ---------------------------------------------------------------------------

class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class ConversationTurn(BaseModel):
    """A single turn in a conversation."""

    role: Role
    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ConversationSession(BaseModel):
    """Full conversation state for a session."""

    session_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# ---------------------------------------------------------------------------
# Job / indexing models
# ---------------------------------------------------------------------------


class IndexingStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IndexingJob(BaseModel):
    """Tracks the progress of a repository indexing job."""

    job_id: str
    repository_url: str
    status: IndexingStatus = IndexingStatus.PENDING
    total_files: int = 0
    processed_files: int = 0
    error_message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def progress_pct(self) -> float:
        if self.total_files == 0:
            return 0.0
        return round(self.processed_files / self.total_files * 100, 1)
