"""FastAPI gateway application factory.

This is the single external-facing service. It:
1. Connects to the Orchestrator as an MCP client (at startup).
2. Exposes REST + WebSocket + SSE endpoints to users.
3. Passes all domain queries to the Orchestrator, which coordinates agents.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from codegraph_shared.logging import configure_logging, get_logger

from .routers import chat, health, index
from .services.orchestrator_client import OrchestratorClient
from .settings import GatewaySettings

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Application factory used by uvicorn ``--factory`` flag."""
    settings = GatewaySettings()
    configure_logging(
        level=settings.log_level,
        service_name=settings.service_name,
        json=settings.log_json,
    )

    orchestrator = OrchestratorClient(settings.orchestrator_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await orchestrator.start()
        app.state.orchestrator = orchestrator
        logger.info("gateway_ready", orchestrator_url=settings.orchestrator_url)
        yield
        await orchestrator.stop()
        logger.info("gateway_shutdown")

    app = FastAPI(
        title="CodeGraph FastAPI Repository Chat",
        description=(
            "Multi-agent system for querying the FastAPI codebase. "
            "Powered by Claude and Neo4j."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat.router)
    app.include_router(index.router)
    app.include_router(health.router)

    return app


if __name__ == "__main__":
    settings = GatewaySettings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        loop="uvloop",
        log_config=None,
    )
