"""Async Redis client for conversation memory and job state.

Built on ``redis.asyncio`` with a simple connection pool. Callers receive a
shared ``Redis`` instance — do **not** close it between requests.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from .logging import get_logger

logger = get_logger(__name__)


def create_redis_client(url: str) -> aioredis.Redis:
    """Create and return a shared async Redis client.

    Args:
        url: Redis connection URL, e.g. ``redis://redis:6379/0``.

    Returns:
        An async ``Redis`` instance backed by a connection pool.
    """
    client: aioredis.Redis = aioredis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    logger.info("redis_client_created", url=url)
    return client
