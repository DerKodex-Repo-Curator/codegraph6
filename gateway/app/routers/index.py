"""Repository indexing API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from codegraph_shared.logging import get_logger

from ..schemas.index import IndexRequest, IndexResponse, IndexStatusResponse
from ..services.orchestrator_client import OrchestratorClient

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["indexing"])


@router.post("/index", response_model=IndexResponse, summary="Trigger repository indexing")
async def start_indexing(body: IndexRequest, request: Request) -> JSONResponse:
    """Start indexing a repository into the knowledge graph.

    The indexing runs asynchronously. Poll ``/api/index/status/{job_id}`` for
    progress updates.
    """
    client: OrchestratorClient = request.app.state.orchestrator
    logger.info("indexing_requested", url=body.repository_url, force=body.force)

    try:
        result = await client.index_repository(body.repository_url, force=body.force)
        return JSONResponse(
            content={
                "job_id": result.get("job_id", "unknown"),
                "status": result.get("status", "pending"),
                "message": "Indexing started in the background",
            }
        )
    except Exception as exc:
        logger.error("indexing_request_failed", error=str(exc))
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get(
    "/index/status/{job_id}",
    response_model=IndexStatusResponse,
    summary="Get indexing job status",
)
async def get_index_status(job_id: str, request: Request) -> JSONResponse:
    """Return the current status of an indexing job."""
    client: OrchestratorClient = request.app.state.orchestrator

    try:
        result = await client.chat(
            f"Get the status of indexing job {job_id}. Use the get_index_status tool.",
            session_id="",
        )
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
