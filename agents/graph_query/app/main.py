"""Graph Query agent entry point."""

from __future__ import annotations

import uvicorn

from codegraph_shared.logging import configure_logging

from .server import create_app
from .settings import GraphQuerySettings

if __name__ == "__main__":
    settings = GraphQuerySettings()
    configure_logging(level=settings.log_level, service_name=settings.service_name, json=settings.log_json)
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        loop="uvloop",
        log_config=None,
    )
