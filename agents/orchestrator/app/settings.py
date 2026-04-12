"""Orchestrator agent configuration."""

from __future__ import annotations

from pydantic import SecretStr

from codegraph_shared.settings import BaseAppSettings


class OrchestratorSettings(BaseAppSettings):
    """Configuration for the Orchestrator MCP agent.

    The orchestrator connects to all child agents via their SSE URLs.
    """

    service_name: str = "orchestrator"
    host: str = "0.0.0.0"
    port: int = 8000

    # Anthropic
    anthropic_api_key: SecretStr = SecretStr("")
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192

    # Child agent SSE URLs
    indexer_url: str = "http://indexer:8001/sse"
    graph_query_url: str = "http://graph_query:8002/sse"
    code_analyst_url: str = "http://code_analyst:8003/sse"

    # Conversation memory settings
    max_history_turns: int = 20
    session_ttl_seconds: int = 86400  # 24 hours

    @property
    def agent_urls(self) -> dict[str, str]:
        """Return a mapping of agent name → SSE URL."""
        return {
            "indexer": self.indexer_url,
            "graph_query": self.graph_query_url,
            "code_analyst": self.code_analyst_url,
        }
