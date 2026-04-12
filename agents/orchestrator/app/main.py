"""Orchestrator agent entry point."""

from __future__ import annotations

import uvicorn

from .server import create_app
from .settings import OrchestratorSettings

if __name__ == "__main__":
    settings = OrchestratorSettings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        loop="uvloop",
        log_config=None,
    )
