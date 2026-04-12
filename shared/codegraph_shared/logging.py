"""Structured logging configuration using structlog.

All agents share this configuration so that log lines are consistent JSON
objects that can be aggregated by any log management platform (Loki, Datadog,
CloudWatch, etc.).

Correlation IDs flow from the gateway through every agent call so that a
single user request can be traced end-to-end in the logs.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

# Context variable holding the current correlation ID.
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the active correlation ID, generating one if absent."""
    cid = _correlation_id.get()
    if not cid:
        cid = uuid.uuid4().hex
        _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """Bind an incoming correlation ID (e.g. from an HTTP header)."""
    _correlation_id.set(cid)


def _add_correlation_id(
    logger: Any,  # noqa: ARG001
    method: str,  # noqa: ARG001
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    event_dict["correlation_id"] = get_correlation_id()
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    service_name: str = "codegraph",
    json: bool = True,
) -> None:
    """Configure structlog for the calling service.

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).
        service_name: Name of this service; added to every log line.
        json: When True (production), emit JSON. When False (dev), emit
            pretty-printed coloured output.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _add_correlation_id,
        structlog.processors.dict_tracebacks,
    ]

    if json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())

    # Silence noisy third-party loggers in production.
    for name in ("httpx", "httpcore", "neo4j", "asyncio", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # Bind the service name to all log records from this process.
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to the given name."""
    return structlog.get_logger(name)
