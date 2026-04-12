"""Typed MCP SSE client helper used by the Orchestrator.

The :class:`AgentRegistry` manages persistent SSE connections to all child
agents.  Each connection is opened once at process startup (via
``AsyncExitStack``) and reused for every request, avoiding the overhead of
SSE handshake negotiation on every tool call.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .exceptions import AgentToolError, AgentUnavailableError
from .logging import get_logger

logger = get_logger(__name__)


class AgentRegistry:
    """Owns all outbound MCP client sessions to child agents.

    Sessions are opened once at startup via :meth:`start` and closed cleanly
    at shutdown via :meth:`stop`.  The registry is process-wide singleton;
    share it through FastAPI's ``app.state`` or dependency injection.

    Args:
        agent_urls: Mapping of agent name → SSE URL,
            e.g. ``{"indexer": "http://indexer:8001/sse"}``.
    """

    def __init__(self, agent_urls: dict[str, str]) -> None:
        self._agent_urls = agent_urls
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        # Cache: agent_name → list of Anthropic-format tool dicts
        self._tool_registry: dict[str, list[dict[str, Any]]] = {}

    async def start(self) -> None:
        """Connect to all agents.  Called during application lifespan startup."""
        await self._exit_stack.__aenter__()
        for name, url in self._agent_urls.items():
            await self._connect(name, url)

    async def _connect(self, name: str, url: str) -> None:
        """Establish a single SSE connection with retry on startup."""
        logger.info("connecting_to_agent", agent=name, url=url)
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(Exception),
                stop=stop_after_attempt(5),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                reraise=True,
            ):
                with attempt:
                    read, write = await self._exit_stack.enter_async_context(
                        sse_client(url)
                    )
                    session = await self._exit_stack.enter_async_context(
                        ClientSession(read, write)
                    )
                    await session.initialize()
                    self._sessions[name] = session
                    logger.info("agent_connected", agent=name)
        except Exception as exc:
            raise AgentUnavailableError(
                f"Could not connect to agent '{name}' at {url}: {exc}"
            ) from exc

        # Discover and cache the agent's tools in Anthropic format.
        response = await self._sessions[name].list_tools()
        self._tool_registry[name] = [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema,
            }
            for t in response.tools
        ]
        logger.info(
            "agent_tools_discovered",
            agent=name,
            tools=[t["name"] for t in self._tool_registry[name]],
        )

    async def stop(self) -> None:
        """Disconnect all agents.  Called during application lifespan shutdown."""
        await self._exit_stack.aclose()
        logger.info("all_agents_disconnected")

    def get_session(self, agent_name: str) -> ClientSession:
        """Retrieve the live session for *agent_name*.

        Raises:
            AgentUnavailableError: If the agent is not registered.
        """
        try:
            return self._sessions[agent_name]
        except KeyError:
            raise AgentUnavailableError(f"Agent '{agent_name}' is not connected")

    def all_anthropic_tools(self) -> list[dict[str, Any]]:
        """Return all agent tools in Anthropic ``messages.create`` format."""
        tools = []
        for agent_tools in self._tool_registry.values():
            tools.extend(agent_tools)
        return tools

    def find_agent_for_tool(self, tool_name: str) -> str:
        """Return the agent name responsible for a given tool.

        Raises:
            KeyError: If no agent advertises this tool.
        """
        for agent_name, tools in self._tool_registry.items():
            if any(t["name"] == tool_name for t in tools):
                return agent_name
        raise KeyError(f"No agent owns tool '{tool_name}'")


async def call_agent_tool(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
) -> Any:
    """Call an MCP tool and return the parsed JSON result.

    Args:
        session: An active :class:`ClientSession`.
        tool_name: Name of the tool to invoke.
        arguments: Tool input parameters.

    Returns:
        Parsed JSON value from the tool's text response.

    Raises:
        AgentToolError: If the tool returns an error.
    """
    logger.debug("calling_agent_tool", tool=tool_name, args=arguments)
    result = await session.call_tool(tool_name, arguments=arguments)

    if result.isError:
        raise AgentToolError(tool_name, result.content)

    # All our tools return a TextContent block with a JSON payload.
    raw = result.content[0].text if result.content else "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Return as plain string if not JSON (e.g. explanations).
        return raw
