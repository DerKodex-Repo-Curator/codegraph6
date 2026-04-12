"""Conversation memory manager backed by Redis.

Stores conversation history as a rolling window of message dicts.
Each session has a configurable TTL to avoid unbounded growth.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from codegraph_shared.logging import get_logger

logger = get_logger(__name__)

_HISTORY_KEY = "chat:history:{session_id}"
_SESSION_KEY = "chat:session:{session_id}"


class ConversationMemory:
    """Redis-backed conversation history manager.

    Args:
        redis: Shared async Redis client.
        max_turns: Rolling window size (number of turns to keep).
        ttl_seconds: Session expiry in seconds.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        max_turns: int = 20,
        ttl_seconds: int = 86400,
    ) -> None:
        self._redis = redis
        self._max_turns = max_turns
        self._ttl = ttl_seconds

    async def load_history(self, session_id: str) -> list[dict[str, Any]]:
        """Return the conversation history for *session_id*.

        Each element is an Anthropic-format message dict with ``role`` and
        ``content`` keys.
        """
        key = _HISTORY_KEY.format(session_id=session_id)
        raw_messages = await self._redis.lrange(key, 0, -1)
        messages: list[dict[str, Any]] = []
        for raw in raw_messages:
            try:
                messages.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("corrupt_history_entry", session_id=session_id)
        return messages

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Append new messages to the session history.

        Applies a rolling window so only the last ``max_turns * 2`` messages
        (user + assistant pairs) are kept.
        """
        key = _HISTORY_KEY.format(session_id=session_id)
        pipe = self._redis.pipeline()
        for msg in messages:
            pipe.rpush(key, json.dumps(msg))
        # Rolling window: keep last max_turns * 2 entries.
        pipe.ltrim(key, -(self._max_turns * 2), -1)
        pipe.expire(key, self._ttl)
        await pipe.execute()
        logger.debug(
            "history_appended",
            session_id=session_id,
            new_messages=len(messages),
        )

    async def clear_session(self, session_id: str) -> None:
        """Delete all history for a session."""
        key = _HISTORY_KEY.format(session_id=session_id)
        await self._redis.delete(key)
        logger.info("session_cleared", session_id=session_id)

    async def session_exists(self, session_id: str) -> bool:
        """Return True if the session has any stored history."""
        key = _HISTORY_KEY.format(session_id=session_id)
        length = await self._redis.llen(key)
        return length > 0
