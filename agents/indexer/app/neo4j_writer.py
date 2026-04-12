"""Batched Neo4j write operations for the indexer.

Uses ``UNWIND`` + ``MERGE`` for idempotent, high-throughput writes.
Re-indexing the same commit is a safe no-op.
"""

from __future__ import annotations

from typing import Any

from codegraph_shared.neo4j_client import Neo4jClient
from codegraph_shared.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Cypher templates
# ---------------------------------------------------------------------------

_UPSERT_FILE = """
UNWIND $batch AS row
MERGE (f:File {path: row.path})
SET f += {module_path: row.module_path, loc: row.loc, language: row.language}
"""

_UPSERT_CLASS = """
UNWIND $batch AS row
MERGE (c:Class {qualified_name: row.qualified_name})
SET c += {
    name: row.name,
    bases: row.bases,
    is_abstract: row.is_abstract,
    docstring: row.docstring,
    start_line: row.start_line,
    end_line: row.end_line
}
"""

_UPSERT_FUNCTION = """
UNWIND $batch AS row
MERGE (f:Function {qualified_name: row.qualified_name})
SET f += {
    name: row.name,
    is_async: row.is_async,
    is_method: row.is_method,
    decorators: row.decorators,
    signature: row.signature,
    docstring: row.docstring,
    source: row.source,
    start_line: row.start_line,
    end_line: row.end_line
}
"""

_UPSERT_ROUTE_LABELS = """
UNWIND $batch AS row
MATCH (f:Function {qualified_name: row.qualified_name})
SET f:Route
SET f += {
    http_method: row.http_method,
    path: row.path,
    response_model: row.response_model,
    status_code: row.status_code,
    tags: row.tags
}
"""

_LINK_FILE_DEFINES_CLASS = """
UNWIND $batch AS row
MATCH (fi:File {path: row.file_path})
MATCH (cl:Class {qualified_name: row.class_qname})
MERGE (fi)-[:DEFINES]->(cl)
"""

_LINK_FILE_DEFINES_FUNCTION = """
UNWIND $batch AS row
MATCH (fi:File {path: row.file_path})
MATCH (fn:Function {qualified_name: row.function_qname})
MERGE (fi)-[:DEFINES]->(fn)
"""

_LINK_INHERITS_FROM = """
UNWIND $batch AS row
MATCH (child:Class {qualified_name: row.from_qname})
MATCH (parent:Class {qualified_name: row.to_qname})
MERGE (child)-[:INHERITS_FROM]->(parent)
"""

_LINK_HAS_METHOD = """
UNWIND $batch AS row
MATCH (cls:Class {qualified_name: row.class_qname})
MATCH (fn:Function {qualified_name: row.method_qname})
MERGE (cls)-[:HAS_METHOD]->(fn)
"""

_LINK_FILE_IMPORTS = """
UNWIND $batch AS row
MATCH (src:File {path: row.src_path})
MATCH (tgt:File {module_path: row.target_module})
MERGE (src)-[:IMPORTS]->(tgt)
"""

_UPSERT_REPOSITORY = """
MERGE (r:Repository {url: $url})
SET r += {name: $name, commit_sha: $commit_sha, indexed_at: datetime()}
"""

_UPSERT_PARAMETER = """
UNWIND $batch AS row
MERGE (p:Parameter {qualified_name: row.qualified_name})
SET p += {name: row.name, type_annotation: row.type_annotation, kind: row.kind}
"""

_LINK_HAS_PARAMETER = """
UNWIND $batch AS row
MATCH (fn:Function {qualified_name: row.function_qname})
MATCH (p:Parameter {qualified_name: row.qualified_name})
MERGE (fn)-[:HAS_PARAMETER]->(p)
"""

_UPSERT_DECORATOR = """
UNWIND $batch AS row
MERGE (d:Decorator {name: row.name})
"""

_LINK_DECORATED_BY = """
UNWIND $batch AS row
MATCH (entity {qualified_name: row.entity_qname})
MATCH (d:Decorator {name: row.decorator_name})
MERGE (entity)-[:DECORATED_BY]->(d)
"""

_UPSERT_IMPORT_NODE = """
UNWIND $batch AS row
MERGE (i:Import {id: row.id})
SET i += {module: row.module, name: row.name, alias: row.alias}
"""

_LINK_FILE_HAS_IMPORT = """
UNWIND $batch AS row
MATCH (f:File {path: row.file_path})
MATCH (i:Import {id: row.import_id})
MERGE (f)-[:HAS_IMPORT]->(i)
"""

_UPSERT_DOCSTRING = """
UNWIND $batch AS row
MERGE (d:Docstring {qualified_name: row.qualified_name})
SET d += {text: row.text, entity_type: row.entity_type}
"""

_LINK_DOCUMENTED_BY = """
UNWIND $batch AS row
MATCH (entity {qualified_name: row.qualified_name})
MATCH (d:Docstring {qualified_name: row.qualified_name})
MERGE (entity)-[:DOCUMENTED_BY]->(d)
"""


class Neo4jIndexWriter:
    """Writes parsed code entities to the Neo4j knowledge graph.

    Args:
        client: An open :class:`Neo4jClient` instance.
        batch_size: Records per write transaction.
    """

    def __init__(self, client: Neo4jClient, batch_size: int = 500) -> None:
        self._db = client
        self._batch_size = batch_size

    async def upsert_repository(
        self, url: str, name: str, commit_sha: str
    ) -> None:
        """Create or update the root Repository node."""
        await self._db.execute_write(
            _UPSERT_REPOSITORY,
            {"url": url, "name": name, "commit_sha": commit_sha},
        )

    async def write_file_entities(
        self, parsed: dict[str, Any], file_path_rel: str
    ) -> None:
        """Write all entities extracted from a single file.

        Args:
            parsed: Dict returned by :func:`parse_file`.
            file_path_rel: Repo-relative file path (for relationship links).
        """
        # Upsert file node.
        await self._db.execute_write_batch(
            _UPSERT_FILE, [parsed["file"]], self._batch_size
        )

        # Classes.
        if parsed["classes"]:
            await self._db.execute_write_batch(
                _UPSERT_CLASS, parsed["classes"], self._batch_size
            )
            class_links = [
                {"file_path": file_path_rel, "class_qname": c["qualified_name"]}
                for c in parsed["classes"]
            ]
            await self._db.execute_write_batch(
                _LINK_FILE_DEFINES_CLASS, class_links, self._batch_size
            )

        # Functions.
        if parsed["functions"]:
            await self._db.execute_write_batch(
                _UPSERT_FUNCTION, parsed["functions"], self._batch_size
            )
            # Apply Route label to handlers.
            routes = [f for f in parsed["functions"] if f.get("is_route")]
            if routes:
                await self._db.execute_write_batch(
                    _UPSERT_ROUTE_LABELS, routes, self._batch_size
                )
            func_links = [
                {
                    "file_path": file_path_rel,
                    "function_qname": f["qualified_name"],
                }
                for f in parsed["functions"]
            ]
            await self._db.execute_write_batch(
                _LINK_FILE_DEFINES_FUNCTION, func_links, self._batch_size
            )

        # Relationships from the visitor.
        inherits = [
            r for r in parsed["relationships"] if r["rel"] == "INHERITS_FROM"
        ]
        if inherits:
            await self._write_inherits(inherits)

        has_methods = [
            r for r in parsed["relationships"] if r["rel"] == "HAS_METHOD"
        ]
        if has_methods:
            await self._write_has_method(has_methods)

        # Parameter nodes.
        if parsed.get("parameters"):
            await self._write_parameters(parsed["parameters"])

        # Decorator nodes.
        if parsed.get("decorator_nodes"):
            await self._write_decorators(
                parsed["decorator_nodes"],
                [r for r in parsed["relationships"] if r["rel"] == "DECORATED_BY"],
            )

        # Import nodes.
        if parsed.get("imports"):
            await self._write_import_nodes(
                parsed["imports"], file_path_rel
            )

        # Docstring nodes.
        if parsed.get("docstring_nodes"):
            await self._write_docstrings(parsed["docstring_nodes"])

    async def _write_inherits(
        self, rels: list[dict[str, str]]
    ) -> None:
        batch = [{"from_qname": r["from"], "to_qname": r["to"]} for r in rels]
        # INHERITS_FROM only works when both classes are indexed; best-effort.
        try:
            await self._db.execute_write_batch(
                _LINK_INHERITS_FROM, batch, self._batch_size
            )
        except Exception as exc:
            logger.warning("inherits_from_skipped", error=str(exc))

    async def _write_has_method(
        self, rels: list[dict[str, str]]
    ) -> None:
        batch = [
            {"class_qname": r["from"], "method_qname": r["to"]} for r in rels
        ]
        try:
            await self._db.execute_write_batch(
                _LINK_HAS_METHOD, batch, self._batch_size
            )
        except Exception as exc:
            logger.warning("has_method_skipped", error=str(exc))

    async def _write_parameters(self, parameters: list[dict[str, Any]]) -> None:
        """Upsert Parameter nodes and link them to their parent functions."""
        try:
            await self._db.execute_write_batch(
                _UPSERT_PARAMETER, parameters, self._batch_size
            )
            await self._db.execute_write_batch(
                _LINK_HAS_PARAMETER, parameters, self._batch_size
            )
        except Exception as exc:
            logger.warning("parameters_skipped", error=str(exc))

    async def _write_decorators(
        self,
        decorator_nodes: list[dict[str, Any]],
        decorated_by_rels: list[dict[str, Any]],
    ) -> None:
        """Upsert Decorator nodes and link them to decorated entities."""
        try:
            await self._db.execute_write_batch(
                _UPSERT_DECORATOR, decorator_nodes, self._batch_size
            )
            if decorated_by_rels:
                link_batch = [
                    {"entity_qname": r["from"], "decorator_name": r["to_decorator"]}
                    for r in decorated_by_rels
                ]
                await self._db.execute_write_batch(
                    _LINK_DECORATED_BY, link_batch, self._batch_size
                )
        except Exception as exc:
            logger.warning("decorators_skipped", error=str(exc))

    async def _write_import_nodes(
        self, imports: list[dict[str, Any]], file_path: str
    ) -> None:
        """Upsert Import nodes and link them to their source file."""
        try:
            await self._db.execute_write_batch(
                _UPSERT_IMPORT_NODE, imports, self._batch_size
            )
            link_batch = [
                {"file_path": file_path, "import_id": imp["id"]}
                for imp in imports
            ]
            await self._db.execute_write_batch(
                _LINK_FILE_HAS_IMPORT, link_batch, self._batch_size
            )
        except Exception as exc:
            logger.warning("import_nodes_skipped", error=str(exc))

    async def _write_docstrings(self, docstring_nodes: list[dict[str, Any]]) -> None:
        """Upsert Docstring nodes and link them to their parent entities."""
        try:
            await self._db.execute_write_batch(
                _UPSERT_DOCSTRING, docstring_nodes, self._batch_size
            )
            await self._db.execute_write_batch(
                _LINK_DOCUMENTED_BY, docstring_nodes, self._batch_size
            )
        except Exception as exc:
            logger.warning("docstrings_skipped", error=str(exc))
