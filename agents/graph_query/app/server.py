"""Graph Query MCP server – tool definitions.

Provides tools for knowledge graph traversal, structured Cypher execution,
and natural language graph queries.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, AsyncIterator

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from codegraph_shared.exceptions import UnsafeCypherError
from codegraph_shared.logging import get_logger
from codegraph_shared.neo4j_client import Neo4jClient

from .query_builder import QueryBuilder, validate_cypher
from .settings import GraphQuerySettings

logger = get_logger(__name__)


@dataclass
class GraphQueryState:
    db: Neo4jClient
    query_builder: QueryBuilder
    settings: GraphQuerySettings


@asynccontextmanager
async def graph_query_lifespan(server: FastMCP) -> AsyncIterator[GraphQueryState]:
    settings = GraphQuerySettings()
    db = Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password.get_secret_value(),
    )
    await db.verify_connectivity()
    qb = QueryBuilder(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.model,
    )
    state = GraphQueryState(db=db, query_builder=qb, settings=settings)
    logger.info("graph_query_ready")
    try:
        yield state
    finally:
        await db.close()


def create_graph_query_server() -> FastMCP:
    """Create and configure the Graph Query MCP server."""
    mcp = FastMCP("graph_query", lifespan=graph_query_lifespan, host="0.0.0.0")

    # -----------------------------------------------------------------------
    # Tool: find_entity
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def find_entity(
        ctx: Context,
        name: Annotated[str, Field(description="Class or function name to search for")],
        kind: Annotated[
            str,
            Field(description="Node kind: 'Class', 'Function', 'File', or 'any'"),
        ] = "any",
        limit: Annotated[int, Field(description="Max results", ge=1, le=50)] = 10,
    ) -> str:
        """Find code entities by name in the knowledge graph.

        Returns a JSON array of matching nodes with their properties.
        """
        state: GraphQueryState = ctx.request_context.lifespan_context
        label = "" if kind == "any" else f":{kind}"
        query = (
            f"MATCH (n{label}) WHERE toLower(n.name) CONTAINS toLower($name) "
            f"RETURN n LIMIT $limit"
        )
        rows = await state.db.execute_read(query, {"name": name, "limit": limit})
        results = [dict(r["n"]) for r in rows]
        return json.dumps(results, default=str)

    # -----------------------------------------------------------------------
    # Tool: get_dependencies
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def get_dependencies(
        ctx: Context,
        qualified_name: Annotated[str, Field(description="Fully qualified name of the entity")],
        depth: Annotated[int, Field(description="Traversal depth (1-5)", ge=1, le=5)] = 2,
    ) -> str:
        """Find what a class or function depends on (imports, calls, inherits).

        Returns a JSON array of dependency relationships.
        """
        state: GraphQueryState = ctx.request_context.lifespan_context
        query = """
        MATCH path = (src {qualified_name: $qname})-[:CALLS|INHERITS_FROM|IMPORTS*1..$depth]->(dep)
        RETURN
            src.qualified_name AS source,
            type(last(relationships(path))) AS rel_type,
            dep.qualified_name AS dependency,
            labels(dep) AS dep_labels
        LIMIT 50
        """
        rows = await state.db.execute_read(
            query, {"qname": qualified_name, "depth": depth}
        )
        return json.dumps(rows, default=str)

    # -----------------------------------------------------------------------
    # Tool: get_dependents
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def get_dependents(
        ctx: Context,
        qualified_name: Annotated[str, Field(description="Fully qualified name of the entity")],
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> str:
        """Find all entities that depend on the given class or function.

        Returns a JSON array of dependent nodes.
        """
        state: GraphQueryState = ctx.request_context.lifespan_context
        query = """
        MATCH (dep)-[:CALLS|INHERITS_FROM|IMPORTS]->(target {qualified_name: $qname})
        RETURN dep.qualified_name AS dependent, labels(dep) AS labels
        LIMIT $limit
        """
        rows = await state.db.execute_read(
            query, {"qname": qualified_name, "limit": limit}
        )
        return json.dumps(rows, default=str)

    # -----------------------------------------------------------------------
    # Tool: trace_imports
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def trace_imports(
        ctx: Context,
        module_path: Annotated[str, Field(description="Dot-path of the module, e.g. 'fastapi.routing'")],
        depth: Annotated[int, Field(ge=1, le=6)] = 3,
    ) -> str:
        """Trace the import chain for a module up to *depth* hops.

        Returns a JSON array of {source, target} pairs forming the import graph.
        """
        state: GraphQueryState = ctx.request_context.lifespan_context
        query = """
        MATCH path = (start:File {module_path: $module})-[:IMPORTS*1..$depth]->(imported:File)
        RETURN
            [n IN nodes(path) | n.module_path] AS chain
        LIMIT 30
        """
        rows = await state.db.execute_read(
            query, {"module": module_path, "depth": depth}
        )
        return json.dumps(rows, default=str)

    # -----------------------------------------------------------------------
    # Tool: find_related
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def find_related(
        ctx: Context,
        qualified_name: Annotated[str, Field(description="Fully qualified name of the entity")],
        relationship: Annotated[
            str,
            Field(description="Relationship type: INHERITS_FROM, HAS_METHOD, CALLS, IMPORTS, DEFINES"),
        ],
        direction: Annotated[
            str, Field(description="'out' (entity→target) or 'in' (target→entity)")
        ] = "out",
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> str:
        """Find entities related to the given entity via a specific relationship type.

        Returns a JSON array of related nodes.
        """
        state: GraphQueryState = ctx.request_context.lifespan_context
        if direction == "out":
            query = (
                f"MATCH (src {{qualified_name: $qname}})-[:{relationship}]->(tgt) "
                f"RETURN tgt LIMIT $limit"
            )
        else:
            query = (
                f"MATCH (tgt)-[:{relationship}]->(src {{qualified_name: $qname}}) "
                f"RETURN tgt LIMIT $limit"
            )
        rows = await state.db.execute_read(
            query, {"qname": qualified_name, "limit": limit}
        )
        results = [dict(r["tgt"]) for r in rows]
        return json.dumps(results, default=str)

    # -----------------------------------------------------------------------
    # Tool: execute_query
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def execute_query(
        ctx: Context,
        query: Annotated[
            str,
            Field(description="READ-ONLY Cypher query. No write clauses allowed."),
        ],
        params: Annotated[
            dict[str, Any],
            Field(description="Named query parameters"),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> str:
        """Execute a custom read-only Cypher query against the knowledge graph.

        The query must not contain CREATE, MERGE, DELETE, SET, REMOVE, or DROP.
        If a LIMIT clause is missing, one is appended automatically.

        Returns a JSON array of result rows.
        """
        state: GraphQueryState = ctx.request_context.lifespan_context
        safe_query = query.strip().rstrip(";")
        try:
            validate_cypher(safe_query)
        except UnsafeCypherError as exc:
            return json.dumps({"error": str(exc)})

        # Append LIMIT if absent.
        if "LIMIT" not in safe_query.upper():
            safe_query = f"{safe_query} LIMIT {limit}"

        try:
            rows = await state.db.execute_read(safe_query, params or {})
            return json.dumps(rows, default=str)
        except Exception as exc:
            logger.error("execute_query_failed", query=safe_query[:200], error=str(exc))
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------------
    # Tool: natural_language_query
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def natural_language_query(
        ctx: Context,
        question: Annotated[
            str,
            Field(description="Natural language question about the codebase"),
        ],
    ) -> str:
        """Convert a natural language question to Cypher and execute it.

        The LLM generates a parameterised Cypher query from the question, which
        is then validated and executed against the knowledge graph.

        Returns a JSON object with ``query``, ``params``, and ``results``.
        """
        state: GraphQueryState = ctx.request_context.lifespan_context
        try:
            cypher, cypher_params = await state.query_builder.build(question)
            # Enforce row limit.
            if "LIMIT" not in cypher.upper():
                cypher = f"{cypher} LIMIT {state.settings.max_query_rows}"
            rows = await state.db.execute_read(cypher, cypher_params)
            return json.dumps({
                "query": cypher,
                "params": cypher_params,
                "results": rows,
            }, default=str)
        except Exception as exc:
            logger.error("nlq_failed", question=question[:100], error=str(exc))
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------------
    # Tool: graph_statistics
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def graph_statistics(ctx: Context) -> str:
        """Return a summary of the knowledge graph: node counts per label.

        Returns a JSON object mapping label → count.
        """
        state: GraphQueryState = ctx.request_context.lifespan_context
        query = """
        CALL db.labels() YIELD label
        CALL apoc.cypher.run('MATCH (n:' + label + ') RETURN count(n) AS cnt', {})
        YIELD value
        RETURN label, value.cnt AS count
        ORDER BY count DESC
        """
        # Fallback if APOC is not installed.
        fallback_query = """
        MATCH (n)
        RETURN labels(n)[0] AS label, count(n) AS count
        ORDER BY count DESC
        LIMIT 20
        """
        try:
            rows = await state.db.execute_read(query, {})
        except Exception:
            rows = await state.db.execute_read(fallback_query, {})
        stats = {r.get("label", "Unknown"): r.get("count", 0) for r in rows}
        return json.dumps(stats, default=str)

    return mcp


def create_app() -> "FastAPI":  # noqa: F821
    """Application factory for uvicorn."""
    from contextlib import asynccontextmanager
    from typing import AsyncIterator

    import uvicorn
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from codegraph_shared.logging import configure_logging

    from .settings import GraphQuerySettings

    settings = GraphQuerySettings()
    configure_logging(level=settings.log_level, service_name=settings.service_name, json=settings.log_json)

    mcp = create_graph_query_server()

    app = FastAPI(title="CodeGraph Graph Query Agent", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.mount("/", mcp.sse_app())
    return app
