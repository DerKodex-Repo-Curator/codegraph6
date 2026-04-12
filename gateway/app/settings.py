"""Gateway configuration."""

from __future__ import annotations

from codegraph_shared.settings import BaseAppSettings


class GatewaySettings(BaseAppSettings):
    """Configuration for the FastAPI gateway."""

    service_name: str = "gateway"
    host: str = "0.0.0.0"
    port: int = 8080

    orchestrator_url: str = "http://orchestrator:8000/sse"
    indexer_url: str = "http://indexer:8001/sse"
    graph_query_url: str = "http://graph_query:8002/sse"
    code_analyst_url: str = "http://code_analyst:8003/sse"

    # CORS
    allow_origins: list[str] = ["*"]
