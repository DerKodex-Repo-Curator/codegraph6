"""Code Analyst MCP server – deep code understanding tools."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, AsyncIterator

import anthropic
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from codegraph_shared.logging import get_logger
from codegraph_shared.neo4j_client import Neo4jClient

from .context_builder import ContextBuilder
from .settings import CodeAnalystSettings

logger = get_logger(__name__)

_ANALYST_SYSTEM = """You are an expert Python code analyst specializing in FastAPI and modern web frameworks.
Given code snippets and metadata from a knowledge graph, you provide:
- Clear, accurate explanations of how code works
- Identification of design patterns and architectural choices
- Analysis of relationships between components
- Insights about best practices and trade-offs

Be concise but thorough. Use code references (module.Class.method) when citing code.
"""


@dataclass
class CodeAnalystState:
    db: Neo4jClient
    context_builder: ContextBuilder
    anthropic_client: anthropic.AsyncAnthropic
    settings: CodeAnalystSettings


@asynccontextmanager
async def code_analyst_lifespan(server: FastMCP) -> AsyncIterator[CodeAnalystState]:
    settings = CodeAnalystSettings()
    db = Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password.get_secret_value(),
    )
    await db.verify_connectivity()
    ctx_builder = ContextBuilder(db)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    state = CodeAnalystState(
        db=db,
        context_builder=ctx_builder,
        anthropic_client=client,
        settings=settings,
    )
    logger.info("code_analyst_ready")
    try:
        yield state
    finally:
        await db.close()


def create_code_analyst_server() -> FastMCP:
    """Create and configure the Code Analyst MCP server."""
    mcp = FastMCP("code_analyst", lifespan=code_analyst_lifespan, host="0.0.0.0")

    # -----------------------------------------------------------------------
    # Tool: analyze_function
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def analyze_function(
        ctx: Context,
        qualified_name: Annotated[
            str,
            Field(description="Fully qualified function name, e.g. 'fastapi.routing.APIRouter.add_api_route'"),
        ],
        focus: Annotated[
            str,
            Field(description="Specific aspect to focus on: 'logic', 'patterns', 'parameters', or 'all'"),
        ] = "all",
    ) -> str:
        """Perform deep analysis of a function's implementation and design.

        Fetches the function's source and context from the graph, then uses
        Claude to generate a detailed explanation.

        Returns a JSON object with ``analysis`` and ``function_meta``.
        """
        state: CodeAnalystState = ctx.request_context.lifespan_context
        context_block = await state.context_builder.get_function_context(qualified_name)

        focus_instruction = {
            "logic": "Focus on the control flow, algorithms, and data transformations.",
            "patterns": "Focus on design patterns, abstractions, and architectural choices.",
            "parameters": "Focus on the parameters, their types, defaults, and validation.",
            "all": "Provide a comprehensive analysis covering logic, patterns, and parameters.",
        }.get(focus, "Provide a comprehensive analysis.")

        prompt = f"""{context_block}

Task: {focus_instruction}

Explain this function clearly for a developer unfamiliar with this codebase.
Include: what it does, how it works, key design decisions, and any caveats."""

        message = await state.anthropic_client.messages.create(
            model=state.settings.model,
            max_tokens=state.settings.max_tokens,
            system=_ANALYST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = message.content[0].text
        return json.dumps({"qualified_name": qualified_name, "analysis": analysis})

    # -----------------------------------------------------------------------
    # Tool: analyze_class
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def analyze_class(
        ctx: Context,
        qualified_name: Annotated[
            str,
            Field(description="Fully qualified class name, e.g. 'fastapi.routing.APIRouter'"),
        ],
    ) -> str:
        """Comprehensive analysis of a class: purpose, design, and key methods.

        Returns a JSON object with ``analysis`` and ``class_meta``.
        """
        state: CodeAnalystState = ctx.request_context.lifespan_context
        context_block = await state.context_builder.get_class_context(qualified_name)

        prompt = f"""{context_block}

Provide a comprehensive analysis of this class:
1. Its primary responsibility and role in the codebase
2. The design pattern(s) it implements
3. Key methods and their purposes
4. How it relates to other parts of the system
5. Notable design decisions"""

        message = await state.anthropic_client.messages.create(
            model=state.settings.model,
            max_tokens=state.settings.max_tokens,
            system=_ANALYST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = message.content[0].text
        return json.dumps({"qualified_name": qualified_name, "analysis": analysis})

    # -----------------------------------------------------------------------
    # Tool: find_patterns
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def find_patterns(
        ctx: Context,
        module_path: Annotated[
            str,
            Field(description="Module to analyze for design patterns, e.g. 'fastapi.routing'"),
        ],
    ) -> str:
        """Identify design patterns in a module.

        Queries the graph for classes and functions, then uses Claude to
        identify patterns like Factory, Decorator, Strategy, etc.

        Returns a JSON object with ``patterns`` (list) and ``analysis``.
        """
        state: CodeAnalystState = ctx.request_context.lifespan_context
        context_block = await state.context_builder.get_module_context(module_path)

        # Also fetch class hierarchy for pattern detection.
        hierarchy_rows = await state.db.execute_read(
            """
            MATCH (f:File {module_path: $module})-[:DEFINES]->(c:Class)
            OPTIONAL MATCH (c)-[:INHERITS_FROM]->(parent:Class)
            RETURN c.name AS name, c.docstring AS docstring,
                   collect(parent.name) AS parents, c.is_abstract AS is_abstract
            LIMIT 20
            """,
            {"module": module_path},
        )

        hierarchy_text = "\n".join(
            f"- `{r['name']}` (abstract: {r['is_abstract']}) "
            f"→ bases: {r['parents'] or 'none'}"
            for r in hierarchy_rows
        )

        prompt = f"""{context_block}

## Class Hierarchy
{hierarchy_text}

Identify all design patterns present in this module. For each pattern:
1. Name the pattern (e.g., Decorator, Factory, Strategy)
2. Which classes/functions implement it
3. Why this pattern was chosen
4. Any trade-offs or caveats"""

        message = await state.anthropic_client.messages.create(
            model=state.settings.model,
            max_tokens=state.settings.max_tokens,
            system=_ANALYST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = message.content[0].text
        return json.dumps({"module": module_path, "analysis": analysis})

    # -----------------------------------------------------------------------
    # Tool: get_code_snippet
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def get_code_snippet(
        ctx: Context,
        qualified_name: Annotated[
            str,
            Field(description="Fully qualified name of the function or class"),
        ],
    ) -> str:
        """Retrieve the raw source code snippet for a function or class.

        Returns a JSON object with ``source``, ``file``, ``start_line``,
        ``end_line``, and ``docstring``.
        """
        state: CodeAnalystState = ctx.request_context.lifespan_context
        rows = await state.db.execute_read(
            """
            MATCH (n {qualified_name: $qname})
            OPTIONAL MATCH (f:File)-[:DEFINES]->(n)
            RETURN n.source AS source, n.docstring AS docstring,
                   n.start_line AS start_line, n.end_line AS end_line,
                   f.path AS file_path
            LIMIT 1
            """,
            {"qname": qualified_name},
        )
        if not rows:
            return json.dumps({"error": f"Entity '{qualified_name}' not found"})
        row = rows[0]
        return json.dumps({
            "qualified_name": qualified_name,
            "source": row.get("source", ""),
            "docstring": row.get("docstring", ""),
            "file": row.get("file_path", ""),
            "start_line": row.get("start_line", 0),
            "end_line": row.get("end_line", 0),
        })

    # -----------------------------------------------------------------------
    # Tool: explain_implementation
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def explain_implementation(
        ctx: Context,
        qualified_name: Annotated[
            str,
            Field(description="Fully qualified name of the entity to explain"),
        ],
        audience: Annotated[
            str,
            Field(description="Target audience: 'beginner', 'intermediate', or 'expert'"),
        ] = "intermediate",
    ) -> str:
        """Generate a narrative explanation of how a piece of code works.

        Tailors the explanation to the specified audience level.

        Returns a JSON object with ``explanation``.
        """
        state: CodeAnalystState = ctx.request_context.lifespan_context

        # Try function first, then class.
        context_block = await state.context_builder.get_function_context(qualified_name)
        if "not found" in context_block:
            context_block = await state.context_builder.get_class_context(qualified_name)

        audience_guidance = {
            "beginner": "Use simple language, avoid jargon, include analogies. Explain every concept.",
            "intermediate": "Assume Python knowledge. Explain framework-specific patterns.",
            "expert": "Be concise. Focus on non-obvious details and edge cases.",
        }.get(audience, "")

        prompt = f"""{context_block}

Audience level: **{audience}**. {audience_guidance}

Explain in detail how this code works and why it is designed this way."""

        message = await state.anthropic_client.messages.create(
            model=state.settings.model,
            max_tokens=state.settings.max_tokens,
            system=_ANALYST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.dumps({
            "qualified_name": qualified_name,
            "audience": audience,
            "explanation": message.content[0].text,
        })

    # -----------------------------------------------------------------------
    # Tool: compare_implementations
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def compare_implementations(
        ctx: Context,
        qualified_name_a: Annotated[str, Field(description="First entity's fully qualified name")],
        qualified_name_b: Annotated[str, Field(description="Second entity's fully qualified name")],
    ) -> str:
        """Compare two code entities: similarities, differences, and trade-offs.

        Returns a JSON object with ``comparison``.
        """
        state: CodeAnalystState = ctx.request_context.lifespan_context

        ctx_a = await state.context_builder.get_function_context(qualified_name_a)
        if "not found" in ctx_a:
            ctx_a = await state.context_builder.get_class_context(qualified_name_a)

        ctx_b = await state.context_builder.get_function_context(qualified_name_b)
        if "not found" in ctx_b:
            ctx_b = await state.context_builder.get_class_context(qualified_name_b)

        prompt = f"""Compare these two code entities:

{ctx_a}

---

{ctx_b}

Provide a structured comparison:
1. Purpose: What does each one do?
2. Similarities: What do they share?
3. Differences: How do they differ in approach, API, or implementation?
4. Trade-offs: When would you use one vs the other?"""

        message = await state.anthropic_client.messages.create(
            model=state.settings.model,
            max_tokens=state.settings.max_tokens,
            system=_ANALYST_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.dumps({
            "entity_a": qualified_name_a,
            "entity_b": qualified_name_b,
            "comparison": message.content[0].text,
        })

    return mcp


def create_app() -> "FastAPI":  # noqa: F821
    """Application factory."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from codegraph_shared.logging import configure_logging
    from .settings import CodeAnalystSettings

    settings = CodeAnalystSettings()
    configure_logging(level=settings.log_level, service_name=settings.service_name, json=settings.log_json)
    mcp = create_code_analyst_server()
    app = FastAPI(title="CodeGraph Code Analyst Agent", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.mount("/", mcp.sse_app())
    return app
