"""Unit tests for the Cypher query safety validator.

These tests do NOT call the Anthropic API – they only test the validation layer.
"""

from __future__ import annotations

import pytest

from agents.graph_query.app.query_builder import validate_cypher
from codegraph_shared.exceptions import UnsafeCypherError


class TestValidateCypher:
    """Tests for the validate_cypher safety function."""

    def test_valid_match_query(self) -> None:
        q = "MATCH (n:Class {name: $name}) RETURN n LIMIT 10"
        assert validate_cypher(q) == q

    def test_valid_with_optional_match(self) -> None:
        q = "MATCH (c:Class) OPTIONAL MATCH (c)-[:HAS_METHOD]->(m) RETURN c, m LIMIT 20"
        assert validate_cypher(q) == q

    def test_rejects_create(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("CREATE (n:Node {x: 1})")

    def test_rejects_merge(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("MERGE (n:Node {x: 1})")

    def test_rejects_delete(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("MATCH (n) DELETE n")

    def test_rejects_detach_delete(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("MATCH (n) DETACH DELETE n")

    def test_rejects_set(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("MATCH (n) SET n.x = 1")

    def test_rejects_remove(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("MATCH (n) REMOVE n.x")

    def test_rejects_drop(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("DROP INDEX my_index")

    def test_case_insensitive_rejection(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("create (n:Node)")

    def test_mixed_case_rejection(self) -> None:
        with pytest.raises(UnsafeCypherError):
            validate_cypher("MeRgE (n:Node {x: 1})")

    def test_full_text_search_query(self) -> None:
        q = (
            "CALL db.index.fulltext.queryNodes('entity_search', $query) "
            "YIELD node, score RETURN node, score LIMIT 10"
        )
        assert validate_cypher(q) == q

    def test_complex_read_query(self) -> None:
        q = """
        MATCH (f:File {module_path: $module})-[:DEFINES]->(c:Class)
        OPTIONAL MATCH (c)-[:INHERITS_FROM]->(parent:Class)
        RETURN c.name, c.docstring, collect(parent.name) AS parents
        ORDER BY c.name
        LIMIT 20
        """
        assert validate_cypher(q) == q
