"""Builds rich context windows for code analysis from Neo4j data.

Fetches source code, docstrings, and relationships from the graph and
assembles them into prompts for the Anthropic API.
"""

from __future__ import annotations

from codegraph_shared.neo4j_client import Neo4jClient
from codegraph_shared.logging import get_logger

logger = get_logger(__name__)


class ContextBuilder:
    """Fetches code entities from Neo4j and formats them for LLM prompts.

    Args:
        db: An open Neo4jClient instance.
    """

    def __init__(self, db: Neo4jClient) -> None:
        self._db = db

    async def get_function_context(self, qualified_name: str) -> str:
        """Build a prompt context block for a function.

        Includes the function source, its docstring, its parent class (if
        any), and the functions it calls.
        """
        rows = await self._db.execute_read(
            """
            MATCH (f:Function {qualified_name: $qname})
            OPTIONAL MATCH (cls:Class)-[:HAS_METHOD]->(f)
            OPTIONAL MATCH (f)-[:CALLS]->(callee:Function)
            RETURN f, cls.qualified_name AS parent_class,
                   collect(callee.qualified_name) AS callees
            """,
            {"qname": qualified_name},
        )
        if not rows:
            return f"Function `{qualified_name}` not found in the knowledge graph."

        row = rows[0]
        func = dict(row["f"])
        parent = row.get("parent_class") or ""
        callees: list[str] = row.get("callees") or []

        lines = [f"## Function: `{func.get('qualified_name', qualified_name)}`\n"]
        if parent:
            lines.append(f"**Defined in class:** `{parent}`\n")
        if func.get("signature"):
            lines.append(f"**Signature:** `{func['name']}({func['signature']})`\n")
        if func.get("docstring"):
            lines.append(f"**Docstring:**\n```\n{func['docstring']}\n```\n")
        if func.get("source"):
            lines.append(f"**Source:**\n```python\n{func['source']}\n```\n")
        if callees:
            lines.append(f"**Calls:** {', '.join(f'`{c}`' for c in callees[:10])}\n")

        return "\n".join(lines)

    async def get_class_context(self, qualified_name: str) -> str:
        """Build a prompt context block for a class including its methods."""
        rows = await self._db.execute_read(
            """
            MATCH (c:Class {qualified_name: $qname})
            OPTIONAL MATCH (c)-[:HAS_METHOD]->(m:Function)
            OPTIONAL MATCH (c)-[:INHERITS_FROM]->(parent:Class)
            RETURN c,
                   collect(DISTINCT m.name) AS methods,
                   collect(DISTINCT parent.qualified_name) AS parents
            """,
            {"qname": qualified_name},
        )
        if not rows:
            return f"Class `{qualified_name}` not found in the knowledge graph."

        row = rows[0]
        cls = dict(row["c"])
        methods: list[str] = row.get("methods") or []
        parents: list[str] = row.get("parents") or []

        lines = [f"## Class: `{cls.get('qualified_name', qualified_name)}`\n"]
        if parents:
            lines.append(f"**Inherits from:** {', '.join(f'`{p}`' for p in parents)}\n")
        if cls.get("docstring"):
            lines.append(f"**Docstring:**\n```\n{cls['docstring']}\n```\n")
        if methods:
            lines.append(f"**Methods:** {', '.join(f'`{m}`' for m in methods[:20])}\n")
        return "\n".join(lines)

    async def get_module_context(self, module_path: str, max_entities: int = 20) -> str:
        """Build a summary context for a module."""
        rows = await self._db.execute_read(
            """
            MATCH (f:File {module_path: $module})
            OPTIONAL MATCH (f)-[:DEFINES]->(cls:Class)
            OPTIONAL MATCH (f)-[:DEFINES]->(fn:Function)
            RETURN f,
                   collect(DISTINCT cls.name)[..$max] AS classes,
                   collect(DISTINCT fn.name)[..$max] AS functions
            """,
            {"module": module_path, "max": max_entities},
        )
        if not rows:
            return f"Module `{module_path}` not found in the knowledge graph."

        row = rows[0]
        file_node = dict(row["f"])
        classes: list[str] = row.get("classes") or []
        functions: list[str] = row.get("functions") or []

        lines = [f"## Module: `{module_path}`\n"]
        lines.append(f"**File:** `{file_node.get('path', '')}`\n")
        if classes:
            lines.append(f"**Classes:** {', '.join(f'`{c}`' for c in classes)}\n")
        if functions:
            lines.append(f"**Functions:** {', '.join(f'`{fn}`' for fn in functions)}\n")
        return "\n".join(lines)
