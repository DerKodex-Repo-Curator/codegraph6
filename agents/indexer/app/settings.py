"""Indexer agent configuration."""

from __future__ import annotations

from pathlib import Path

from codegraph_shared.settings import BaseAppSettings


class IndexerSettings(BaseAppSettings):
    """Configuration for the Indexer MCP agent.

    Attributes:
        service_name: Service identifier used in logs.
        host: Address to bind the SSE server to.
        port: Port for the SSE server.
        repo_clone_dir: Local directory for cloning repositories.
        default_repo_url: Default FastAPI repository URL.
        embedding_model: OpenAI embedding model for vector creation.
        anthropic_api_key: Anthropic API key for embedding/analysis.
        batch_size: Number of nodes to write per Neo4j transaction.
    """

    service_name: str = "indexer"
    host: str = "0.0.0.0"
    port: int = 8001

    repo_clone_dir: Path = Path("/tmp/repos")
    default_repo_url: str = "https://github.com/tiangolo/fastapi"

    anthropic_api_key: str = ""
    batch_size: int = 500
