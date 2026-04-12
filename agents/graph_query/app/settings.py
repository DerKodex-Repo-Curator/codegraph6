"""Graph Query agent configuration."""

from __future__ import annotations

from pydantic import SecretStr

from codegraph_shared.settings import BaseAppSettings


class GraphQuerySettings(BaseAppSettings):
    """Configuration for the Graph Query MCP agent."""

    service_name: str = "graph_query"
    host: str = "0.0.0.0"
    port: int = 8002

    anthropic_api_key: SecretStr = SecretStr("")
    model: str = "claude-3-5-haiku-20241022"  # cheaper model for Cypher generation

    # Safety: maximum rows returned by any query.
    max_query_rows: int = 100
