"""Code Analyst agent entry point."""

from __future__ import annotations

import uvicorn

from .server import create_app
from .settings import CodeAnalystSettings

if __name__ == "__main__":
    settings = CodeAnalystSettings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        loop="uvloop",
        log_config=None,
    )
