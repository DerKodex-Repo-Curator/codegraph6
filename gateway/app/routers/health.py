"""Health and observability endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from codegraph_shared.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["observability"])


@router.get("/health", summary="Gateway health check")
async def health() -> JSONResponse:
    """Return 200 if the gateway is running."""
    return JSONResponse({"status": "ok", "service": "gateway"})


@router.get("/api/agents/health", summary="Health check for all agents")
async def agents_health(request: Request) -> JSONResponse:
    """Check connectivity to all agents via the Orchestrator.

    Returns a dict mapping agent name → connection status.
    """
    from ..services.orchestrator_client import OrchestratorClient

    client: OrchestratorClient = request.app.state.orchestrator
    try:
        status = await client.get_agent_statuses()
        return JSONResponse(content={"status": "ok", "agents": status})
    except Exception as exc:
        logger.error("health_check_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "error": str(exc)},
        )


@router.get("/api/graph/statistics", summary="Knowledge graph node counts")
async def graph_statistics(request: Request) -> JSONResponse:
    """Return statistics from the Neo4j knowledge graph."""
    from ..services.orchestrator_client import OrchestratorClient

    client: OrchestratorClient = request.app.state.orchestrator
    try:
        result = await client.chat(
            "Return graph statistics using the graph_statistics tool. "
            "Just call the tool and return the result directly.",
            session_id="",
        )
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
