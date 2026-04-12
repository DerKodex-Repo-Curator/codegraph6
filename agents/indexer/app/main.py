"""Indexer agent entry point.

Mounts the MCP SSE app alongside a FastAPI health endpoint so Docker
health checks can probe the service without parsing SSE streams.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from codegraph_shared.logging import configure_logging

from .server import create_indexer_server
from .settings import IndexerSettings


def create_app() -> FastAPI:
    """Application factory used by uvicorn ``--factory`` flag."""
    settings = IndexerSettings()
    configure_logging(
        level=settings.log_level,
        service_name=settings.service_name,
        json=settings.log_json,
    )

    mcp = create_indexer_server()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(
        title="CodeGraph Indexer Agent",
        description="MCP server for repository indexing",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount MCP SSE app at root; it exposes /sse and /messages/.
    app.mount("/", mcp.sse_app())

    return app


if __name__ == "__main__":
    settings = IndexerSettings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        loop="uvloop",
        log_config=None,  # Suppress uvicorn's default logging; structlog handles it.
    )
