"""Orchestrator MCP server – central coordinator for the multi-agent system.

This server is simultaneously:
- An MCP **server**: exposes tools to the FastAPI gateway.
- An MCP **client**: connects to and calls tools on child agents.

The tool-use loop is driven by Claude (via the Anthropic API), which selects
which child agent tools to call based on the user's question.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, AsyncIterator

import anthropic
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from codegraph_shared.logging import get_logger
from codegraph_shared.mcp_client import AgentRegistry
from codegraph_shared.redis_client import create_redis_client

from .memory import ConversationMemory
from .planner import Planner
from .settings import OrchestratorSettings

logger = get_logger(__name__)


@dataclass
class OrchestratorState:
    """Runtime state held for the duration of the process."""

    registry: AgentRegistry
    memory: ConversationMemory
    planner: Planner
    settings: OrchestratorSettings


@asynccontextmanager
async def orchestrator_lifespan(server: FastMCP) -> AsyncIterator[OrchestratorState]:
    """Open connections to all child agents and infrastructure on startup."""
    settings = OrchestratorSettings()

    # Connect to child agents.
    registry = AgentRegistry(settings.agent_urls)
    await registry.start()

    # Connect to Redis for conversation memory.
    redis = create_redis_client(settings.redis_url)
    memory = ConversationMemory(
        redis,
        max_turns=settings.max_history_turns,
        ttl_seconds=settings.session_ttl_seconds,
    )

    # Create the Anthropic client and planner.
    anthropic_client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value()
    )
    planner = Planner(
        anthropic_client=anthropic_client,
        registry=registry,
        memory=memory,
        model=settings.model,
        max_tokens=settings.max_tokens,
    )

    state = OrchestratorState(
        registry=registry,
        memory=memory,
        planner=planner,
        settings=settings,
    )
    logger.info("orchestrator_ready", agents=list(settings.agent_urls.keys()))

    try:
        yield state
    finally:
        await registry.stop()
        await redis.aclose()


def create_orchestrator_server() -> FastMCP:
    """Create and configure the Orchestrator MCP server."""
    mcp = FastMCP("orchestrator", lifespan=orchestrator_lifespan, host="0.0.0.0")

    # -----------------------------------------------------------------------
    # Tool: answer_question
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def answer_question(
        ctx: Context,
        question: Annotated[
            str,
            Field(description="The user's question about the FastAPI codebase"),
        ],
        session_id: Annotated[
            str,
            Field(description="Session ID for conversation continuity. Generate a UUID if not provided."),
        ] = "",
    ) -> str:
        """Answer a question about the FastAPI codebase using multi-agent collaboration.

        Orchestrates calls to the Indexer, Graph Query, and Code Analyst agents
        to produce a comprehensive, accurate response.

        Returns a JSON object with ``answer``, ``session_id``, and ``agents_used``.
        """
        state: OrchestratorState = ctx.request_context.lifespan_context

        sid = session_id or uuid.uuid4().hex
        logger.info("answering_question", session_id=sid, question=question[:100])

        answer = await state.planner.run(session_id=sid, question=question)

        return json.dumps({"answer": answer, "session_id": sid})

    # -----------------------------------------------------------------------
    # Tool: analyze_query
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def analyze_query(
        ctx: Context,
        query: Annotated[str, Field(description="Raw user query to classify")],
    ) -> str:
        """Classify a query's intent and extract key code entities mentioned.

        Returns a JSON object with:
        - ``intent``: one of 'find_entity', 'explain_code', 'trace_dependency',
          'find_pattern', 'index_repo', 'general'
        - ``entities``: list of code entity names found in the query
        - ``complexity``: 'simple', 'medium', or 'complex'
        """
        state: OrchestratorState = ctx.request_context.lifespan_context
        anthropic_client = state.planner._client

        prompt = f"""Analyze this query about a Python codebase and return JSON only.

Query: {query}

Return JSON with these exact keys:
- "intent": one of ["find_entity", "explain_code", "trace_dependency", "find_pattern", "index_repo", "general"]
- "entities": list of code entity names (class/function names) mentioned
- "complexity": one of ["simple", "medium", "complex"]
- "suggested_agents": list of agents to use from ["indexer", "graph_query", "code_analyst"]"""

        response = await anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Attempt to parse and re-serialize for validation.
        try:
            parsed = json.loads(raw)
            return json.dumps(parsed)
        except json.JSONDecodeError:
            return json.dumps({
                "intent": "general",
                "entities": [],
                "complexity": "medium",
                "suggested_agents": ["graph_query", "code_analyst"],
            })

    # -----------------------------------------------------------------------
    # Tool: route_to_agents
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def route_to_agents(
        ctx: Context,
        question: Annotated[str, Field(description="The user question to route")],
        analysis: Annotated[
            str,
            Field(description="JSON analysis from analyze_query"),
        ],
    ) -> str:
        """Determine which agents should handle the question and in what order.

        Returns a JSON object with ``routing_plan`` (list of agent names in
        execution order) and ``rationale``.
        """
        state: OrchestratorState = ctx.request_context.lifespan_context
        available = list(state.settings.agent_urls.keys())

        try:
            analysis_dict = json.loads(analysis)
        except json.JSONDecodeError:
            analysis_dict = {}

        suggested = analysis_dict.get("suggested_agents", available)
        # Filter to only available agents.
        plan = [a for a in suggested if a in available]
        if not plan:
            plan = ["graph_query"]  # Safe default.

        return json.dumps({
            "routing_plan": plan,
            "rationale": f"Based on query analysis: intent={analysis_dict.get('intent')}, "
                         f"complexity={analysis_dict.get('complexity')}",
        })

    # -----------------------------------------------------------------------
    # Tool: get_conversation_context
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def get_conversation_context(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session ID to retrieve history for")],
        last_n: Annotated[int, Field(description="Number of recent turns to return", ge=1, le=20)] = 5,
    ) -> str:
        """Retrieve recent conversation history for a session.

        Returns a JSON object with ``session_id``, ``turns`` (list of
        role/content dicts), and ``exists`` (bool).
        """
        state: OrchestratorState = ctx.request_context.lifespan_context
        history = await state.memory.load_history(session_id)
        recent = history[-(last_n * 2):]  # Keep last N pairs.
        return json.dumps({
            "session_id": session_id,
            "exists": bool(history),
            "turns": recent,
            "total_turns": len(history),
        })

    # -----------------------------------------------------------------------
    # Tool: synthesize_response
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def synthesize_response(
        ctx: Context,
        question: Annotated[str, Field(description="Original user question")],
        agent_outputs: Annotated[
            str,
            Field(description="JSON array of {agent, output} objects from the invoked agents"),
        ],
    ) -> str:
        """Synthesize a coherent final response from multiple agent outputs.

        Uses Claude to merge, deduplicate, and format the raw agent outputs
        into a user-friendly answer.

        Returns a JSON object with ``synthesized_answer``.
        """
        state: OrchestratorState = ctx.request_context.lifespan_context
        anthropic_client = state.planner._client

        prompt = f"""You received outputs from multiple specialized agents for this question:

**Question:** {question}

**Agent outputs:**
{agent_outputs}

Synthesize a single, coherent, well-formatted answer. Avoid repeating the same
information. Use markdown formatting where helpful. Cite specific code entities
(module.Class.method) found by the agents."""

        response = await anthropic_client.messages.create(
            model=state.settings.model,
            max_tokens=state.settings.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.dumps({"synthesized_answer": response.content[0].text})

    return mcp


def create_app() -> "FastAPI":  # noqa: F821
    """Application factory for uvicorn."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from codegraph_shared.logging import configure_logging
    from .settings import OrchestratorSettings

    settings = OrchestratorSettings()
    configure_logging(level=settings.log_level, service_name=settings.service_name, json=settings.log_json)
    mcp = create_orchestrator_server()
    app = FastAPI(title="CodeGraph Orchestrator Agent", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.mount("/", mcp.sse_app())
    return app
