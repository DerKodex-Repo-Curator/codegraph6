"""Gateway-side MCP client for the Orchestrator agent.

The gateway connects to the Orchestrator via MCP SSE, then calls tools on it
exactly as the Orchestrator calls tools on its child agents.  This creates the
full chain:

  User → Gateway (HTTP) → Orchestrator (MCP) → Child Agents (MCP) → Neo4j
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.sse import sse_client
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from codegraph_shared.exceptions import AgentUnavailableError
from codegraph_shared.logging import get_logger

logger = get_logger(__name__)


class OrchestratorClient:
    """MCP client that connects to the Orchestrator agent.

    Keeps a persistent SSE connection open for the lifetime of the gateway
    process.  Use :meth:`start` / :meth:`stop` from the FastAPI lifespan.

    Args:
        orchestrator_url: SSE URL of the Orchestrator agent.
    """

    def __init__(self, orchestrator_url: str) -> None:
        self._url = orchestrator_url
        self._exit_stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def start(self) -> None:
        """Connect to the Orchestrator.  Called once at gateway startup."""
        logger.info("connecting_to_orchestrator", url=self._url)
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(Exception),
                stop=stop_after_attempt(10),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                reraise=True,
            ):
                with attempt:
                    await self._exit_stack.__aenter__()
                    read, write = await self._exit_stack.enter_async_context(
                        sse_client(self._url)
                    )
                    session = await self._exit_stack.enter_async_context(
                        ClientSession(read, write)
                    )
                    await session.initialize()
                    self._session = session
                    logger.info("orchestrator_connected")
        except Exception as exc:
            raise AgentUnavailableError(
                f"Cannot connect to orchestrator at {self._url}: {exc}"
            ) from exc

    async def stop(self) -> None:
        """Disconnect from the Orchestrator."""
        await self._exit_stack.aclose()
        logger.info("orchestrator_disconnected")

    async def chat(self, message: str, session_id: str = "") -> dict:
        """Send a question and receive the answer.

        Args:
            message: User's question.
            session_id: Conversation session ID (empty → new session).

        Returns:
            Dict with ``answer`` and ``session_id``.
        """
        if self._session is None:
            raise AgentUnavailableError("Orchestrator session is not open")

        result = await self._session.call_tool(
            "answer_question",
            arguments={"question": message, "session_id": session_id},
        )
        if result.isError:
            raise RuntimeError(f"Orchestrator error: {result.content}")

        raw = result.content[0].text if result.content else "{}"
        return json.loads(raw)

    async def get_agent_statuses(self) -> dict:
        """Return health status from all child agents via the orchestrator."""
        if self._session is None:
            return {"status": "orchestrator_not_connected"}

        tools_response = await self._session.list_tools()
        return {
            "orchestrator": "connected",
            "available_tools": [t.name for t in tools_response.tools],
        }

    async def index_repository(self, url: str, force: bool = False) -> dict:
        """Trigger repository indexing via the Indexer agent."""
        if self._session is None:
            raise AgentUnavailableError("Orchestrator session is not open")

        # The orchestrator exposes the indexer tools transparently through its
        # tool-use loop, but for direct indexing we call the indexer indirectly
        # by asking the orchestrator to do it.
        result = await self._session.call_tool(
            "answer_question",
            arguments={
                "question": f"Please index the repository at {url}. Use the index_repository tool.",
                "session_id": "",
            },
        )
        if result.isError:
            raise RuntimeError(f"Indexing error: {result.content}")
        raw = result.content[0].text if result.content else "{}"
        return json.loads(raw)
