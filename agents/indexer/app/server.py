"""Indexer MCP server – tool definitions and request handlers.

This module wires together the AST parser, Neo4j writer, and job state manager
into MCP tool handlers that are registered on the FastMCP server instance.

The server is created once (in ``main.py``) and shared across all SSE
connections via the FastMCP lifespan mechanism.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, AsyncIterator

import git
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from codegraph_shared.logging import get_logger
from codegraph_shared.models import IndexingJob, IndexingStatus
from codegraph_shared.neo4j_client import Neo4jClient
from codegraph_shared.redis_client import create_redis_client

from .neo4j_writer import Neo4jIndexWriter
from .parsers.python_ast import parse_file
from .settings import IndexerSettings

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Lifespan state
# ---------------------------------------------------------------------------


@dataclass
class IndexerState:
    """Holds runtime dependencies for the indexer agent."""

    db: Neo4jClient
    writer: Neo4jIndexWriter
    settings: IndexerSettings
    jobs: dict[str, IndexingJob] = field(default_factory=dict)


@asynccontextmanager
async def indexer_lifespan(server: FastMCP) -> AsyncIterator[IndexerState]:
    """Open database connections on startup; close on shutdown."""
    settings = IndexerSettings()
    db = Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password.get_secret_value(),
    )
    await db.verify_connectivity()
    writer = Neo4jIndexWriter(db, batch_size=settings.batch_size)
    state = IndexerState(db=db, writer=writer, settings=settings)
    logger.info("indexer_ready")
    try:
        yield state
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------


def create_indexer_server() -> FastMCP:
    """Create and configure the Indexer MCP server."""
    mcp = FastMCP("indexer", lifespan=indexer_lifespan, host="0.0.0.0")

    # -----------------------------------------------------------------------
    # Tool: index_repository
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def index_repository(
        ctx: Context,
        repository_url: Annotated[
            str,
            Field(description="Git URL of the repository to index (HTTPS or SSH)"),
        ] = "",
        force: Annotated[
            bool,
            Field(description="If True, re-index even if the commit SHA matches"),
        ] = False,
    ) -> str:
        """Clone a repository and index all Python files into the knowledge graph.

        Returns a JSON object with ``job_id`` and initial ``status``.
        """
        state: IndexerState = ctx.request_context.lifespan_context
        url = repository_url or state.settings.default_repo_url

        job_id = uuid.uuid4().hex
        job = IndexingJob(job_id=job_id, repository_url=url)
        state.jobs[job_id] = job

        # Run indexing in the background so the tool returns immediately.
        asyncio.create_task(_run_indexing(job, state, force=force))

        logger.info("indexing_started", job_id=job_id, url=url)
        return json.dumps({"job_id": job_id, "status": job.status})

    # -----------------------------------------------------------------------
    # Tool: get_index_status
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def get_index_status(
        ctx: Context,
        job_id: Annotated[str, Field(description="Job ID returned by index_repository")],
    ) -> str:
        """Return the current status of an indexing job.

        Returns a JSON object with ``job_id``, ``status``, ``progress_pct``,
        ``processed_files``, ``total_files``, and ``error_message``.
        """
        state: IndexerState = ctx.request_context.lifespan_context
        job = state.jobs.get(job_id)
        if not job:
            return json.dumps({"error": f"Job '{job_id}' not found"})
        return job.model_dump_json()

    # -----------------------------------------------------------------------
    # Tool: index_file
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def index_file(
        ctx: Context,
        file_path: Annotated[str, Field(description="Absolute path to a .py file")],
        repo_root: Annotated[str, Field(description="Absolute path to the repository root")],
        module_prefix: Annotated[str, Field(description="Dot-prefix for qualified names, e.g. 'fastapi'")] = "",
    ) -> str:
        """Parse and index a single Python file.

        Returns a summary of entities written to the graph.
        """
        state: IndexerState = ctx.request_context.lifespan_context
        try:
            parsed = parse_file(
                Path(file_path), Path(repo_root), module_prefix=module_prefix
            )
            await state.writer.write_file_entities(parsed, parsed["file"]["path"])
            return json.dumps({
                "status": "ok",
                "file": parsed["file"]["path"],
                "classes": len(parsed["classes"]),
                "functions": len(parsed["functions"]),
            })
        except Exception as exc:
            logger.error("index_file_failed", path=file_path, error=str(exc))
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------------
    # Tool: parse_python_ast
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def parse_python_ast(
        code: Annotated[str, Field(description="Python source code to parse")],
        module_name: Annotated[str, Field(description="Module path for qualified names")] = "unknown",
    ) -> str:
        """Parse raw Python source and return extracted entities as JSON.

        Useful for one-off analysis without writing to the graph.
        """
        import ast
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mktemp(suffix=".py"))
        tmp.write_text(code)
        try:
            parsed = parse_file(tmp, tmp.parent, module_prefix=module_name)
            return json.dumps({
                "classes": parsed["classes"],
                "functions": parsed["functions"],
                "imports": parsed["imports"],
            }, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        finally:
            tmp.unlink(missing_ok=True)

    # -----------------------------------------------------------------------
    # Tool: extract_entities
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def extract_entities(
        ctx: Context,
        module_path: Annotated[str, Field(description="Dot-path of the module, e.g. 'fastapi.routing'")],
    ) -> str:
        """List all entities (classes and functions) in a given module from the graph.

        Returns a JSON object with ``classes`` and ``functions`` arrays.
        """
        state: IndexerState = ctx.request_context.lifespan_context
        classes = await state.db.execute_read(
            "MATCH (c:Class) WHERE c.qualified_name STARTS WITH $prefix RETURN c",
            {"prefix": module_path},
        )
        functions = await state.db.execute_read(
            "MATCH (f:Function) WHERE f.qualified_name STARTS WITH $prefix RETURN f",
            {"prefix": module_path},
        )
        return json.dumps({
            "classes": [dict(r["c"]) for r in classes],
            "functions": [dict(r["f"]) for r in functions],
        }, default=str)

    return mcp


# ---------------------------------------------------------------------------
# Background indexing task
# ---------------------------------------------------------------------------


async def _run_indexing(
    job: IndexingJob, state: IndexerState, *, force: bool = False
) -> None:
    """Clone the repo and index all Python files.  Runs as a background task."""
    settings = state.settings
    clone_dir = settings.repo_clone_dir / job.job_id
    clone_dir.mkdir(parents=True, exist_ok=True)

    try:
        job.status = IndexingStatus.RUNNING

        # --- Clone or pull -------------------------------------------------
        logger.info("cloning_repo", url=job.repository_url, dest=str(clone_dir))
        try:
            repo = git.Repo.clone_from(job.repository_url, clone_dir, depth=1)
        except git.GitCommandError as exc:
            raise RuntimeError(f"Clone failed: {exc}") from exc

        commit_sha = repo.head.commit.hexsha
        repo_name = job.repository_url.rstrip("/").split("/")[-1]

        # Check if already indexed at this SHA.
        if not force:
            existing = await state.db.execute_read(
                "MATCH (r:Repository {url: $url}) RETURN r.commit_sha AS sha",
                {"url": job.repository_url},
            )
            if existing and existing[0].get("sha") == commit_sha:
                job.status = IndexingStatus.COMPLETED
                job.processed_files = job.total_files
                logger.info("already_indexed", sha=commit_sha)
                return

        await state.writer.upsert_repository(
            url=job.repository_url, name=repo_name, commit_sha=commit_sha
        )

        # --- Walk Python files ---------------------------------------------
        py_files = list(clone_dir.rglob("*.py"))
        # Exclude test files and vendored code for leaner graph.
        py_files = [
            f for f in py_files
            if "test" not in f.parts and ".git" not in f.parts
        ]
        job.total_files = len(py_files)
        logger.info("files_found", count=job.total_files)

        # Determine module prefix from top-level package directory.
        module_prefix = _detect_module_prefix(clone_dir)

        for idx, py_file in enumerate(py_files):
            try:
                parsed = parse_file(py_file, clone_dir, module_prefix=module_prefix)
                await state.writer.write_file_entities(
                    parsed, parsed["file"]["path"]
                )
            except Exception as exc:
                logger.warning("file_skipped", path=str(py_file), error=str(exc))

            job.processed_files = idx + 1
            if (idx + 1) % 50 == 0:
                logger.info("indexing_progress", done=idx + 1, total=job.total_files)

        job.status = IndexingStatus.COMPLETED
        logger.info("indexing_complete", job_id=job.job_id, total=job.total_files)

    except Exception as exc:
        job.status = IndexingStatus.FAILED
        job.error_message = str(exc)
        logger.error("indexing_failed", job_id=job.job_id, error=str(exc))
    finally:
        # Clean up clone directory to save disk space.
        shutil.rmtree(clone_dir, ignore_errors=True)


def _detect_module_prefix(repo_root: Path) -> str:
    """Best-effort detection of the top-level Python package name."""
    for child in sorted(repo_root.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            return child.name
    return ""
