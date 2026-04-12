"""Integration tests for the Indexer agent.

These tests require Neo4j to be running.  They use testcontainers to spin up
a fresh Neo4j instance for each test session.

Run with:
    pytest tests/integration/ -m integration
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

# Integration tests are skipped unless Neo4j is available.
pytest.importorskip("testcontainers")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def neo4j_container():
    """Spin up a Neo4j container for the test session."""
    from testcontainers.neo4j import Neo4jContainer  # type: ignore

    with Neo4jContainer("neo4j:5.26-community") as container:
        yield container


@pytest_asyncio.fixture
async def neo4j_client(neo4j_container):
    from codegraph_shared.neo4j_client import Neo4jClient

    client = Neo4jClient(
        uri=neo4j_container.get_connection_url(),
        user="neo4j",
        password="password",
    )
    await client.verify_connectivity()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_write_and_read_file_entities(neo4j_client) -> None:
    """Write parsed entities from a temp file and verify they land in Neo4j."""
    from agents.indexer.app.parsers.python_ast import parse_file
    from agents.indexer.app.neo4j_writer import Neo4jIndexWriter

    writer = Neo4jIndexWriter(neo4j_client, batch_size=100)

    source = """
class Greeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"
"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = root / "greeter.py"
        f.write_text(source)
        parsed = parse_file(f, root, module_prefix="myapp")
        await writer.write_file_entities(parsed, parsed["file"]["path"])

    # Verify class was written.
    rows = await neo4j_client.execute_read(
        "MATCH (c:Class {name: 'Greeter'}) RETURN c"
    )
    assert len(rows) == 1
    assert rows[0]["c"]["name"] == "Greeter"

    # Verify method was written.
    rows = await neo4j_client.execute_read(
        "MATCH (fn:Function {name: 'greet'}) RETURN fn"
    )
    assert len(rows) == 1
    assert rows[0]["fn"]["is_method"] is True


@pytest.mark.asyncio
async def test_upsert_is_idempotent(neo4j_client) -> None:
    """Writing the same entities twice should not create duplicates."""
    from agents.indexer.app.parsers.python_ast import parse_file
    from agents.indexer.app.neo4j_writer import Neo4jIndexWriter

    writer = Neo4jIndexWriter(neo4j_client, batch_size=100)

    source = 'class IdempotentClass:\n    pass\n'
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = root / "idem.py"
        f.write_text(source)
        parsed = parse_file(f, root)

        # Write twice.
        await writer.write_file_entities(parsed, parsed["file"]["path"])
        await writer.write_file_entities(parsed, parsed["file"]["path"])

    rows = await neo4j_client.execute_read(
        "MATCH (c:Class {name: 'IdempotentClass'}) RETURN count(c) AS cnt"
    )
    assert rows[0]["cnt"] == 1
