"""Custom exception hierarchy for the CodeGraph multi-agent system."""

from __future__ import annotations


class CodeGraphError(Exception):
    """Base exception for all CodeGraph errors."""

    def __init__(self, message: str, *, context: dict | None = None) -> None:
        super().__init__(message)
        self.context = context or {}


# ---------------------------------------------------------------------------
# Agent errors
# ---------------------------------------------------------------------------


class AgentError(CodeGraphError):
    """Raised when an agent fails to process a request."""


class AgentTimeoutError(AgentError):
    """Raised when an agent call exceeds its configured timeout."""


class AgentToolError(AgentError):
    """Raised when an MCP tool call returns an error result.

    Args:
        tool_name: The name of the failing tool.
        raw_content: Raw error content returned by the tool.
    """

    def __init__(self, tool_name: str, raw_content: object) -> None:
        super().__init__(
            f"Tool '{tool_name}' returned an error",
            context={"tool_name": tool_name, "raw_content": str(raw_content)},
        )
        self.tool_name = tool_name
        self.raw_content = raw_content


class AgentUnavailableError(AgentError):
    """Raised when an agent is unreachable or its circuit breaker is open."""


# ---------------------------------------------------------------------------
# Graph errors
# ---------------------------------------------------------------------------


class GraphError(CodeGraphError):
    """Base class for knowledge graph errors."""


class GraphQueryError(GraphError):
    """Raised when a Cypher query fails."""


class GraphWriteError(GraphError):
    """Raised when a graph write operation fails."""


class UnsafeCypherError(GraphError):
    """Raised when a generated Cypher query contains write clauses."""

    def __init__(self, query: str) -> None:
        super().__init__(
            "LLM-generated Cypher contains forbidden write clauses",
            context={"query": query[:500]},
        )


# ---------------------------------------------------------------------------
# Indexer errors
# ---------------------------------------------------------------------------


class IndexerError(CodeGraphError):
    """Base class for indexer errors."""


class RepositoryCloneError(IndexerError):
    """Raised when repository cloning fails."""


class ParseError(IndexerError):
    """Raised when AST parsing fails for a file."""

    def __init__(self, file_path: str, cause: Exception) -> None:
        super().__init__(
            f"Failed to parse {file_path}: {cause}",
            context={"file_path": file_path},
        )
        self.__cause__ = cause


# ---------------------------------------------------------------------------
# Conversation / Memory errors
# ---------------------------------------------------------------------------


class MemoryError(CodeGraphError):
    """Raised when conversation memory operations fail."""


class SessionNotFoundError(MemoryError):
    """Raised when a requested session ID does not exist."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session '{session_id}' not found")
        self.session_id = session_id


# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------


class ConfigurationError(CodeGraphError):
    """Raised when required configuration is missing or invalid."""
