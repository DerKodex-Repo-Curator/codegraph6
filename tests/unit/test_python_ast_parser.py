"""Unit tests for the Python AST parser.

These tests run without any external dependencies (no Neo4j, no Redis,
no Anthropic API) and should be fast and deterministic.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agents.indexer.app.parsers.python_ast import parse_file, _path_to_module


class TestParseFile:
    """Tests for the parse_file function."""

    def _write_and_parse(self, source: str, module_prefix: str = "") -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "test_module.py"
            file.write_text(source)
            return parse_file(file, root, module_prefix=module_prefix)

    def test_extracts_file_metadata(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        assert result["file"]["language"] == "python"
        assert result["file"]["module_path"] == "test_module"
        assert result["file"]["loc"] > 0

    def test_extracts_classes(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        class_names = [c["name"] for c in result["classes"]]
        assert "MyModel" in class_names
        assert "ExtendedModel" in class_names

    def test_class_docstring_extracted(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        my_model = next(c for c in result["classes"] if c["name"] == "MyModel")
        assert "simple model class" in my_model["docstring"]

    def test_class_inheritance(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        extended = next(c for c in result["classes"] if c["name"] == "ExtendedModel")
        assert "MyModel" in extended["bases"]

    def test_extracts_functions(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        func_names = [f["name"] for f in result["functions"]]
        assert "get_item" in func_names
        assert "create_item" in func_names
        assert "__init__" in func_names
        assert "compute" in func_names

    def test_async_function_detected(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        get_item = next(f for f in result["functions"] if f["name"] == "get_item")
        assert get_item["is_async"] is True

    def test_method_detected(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        compute = next(f for f in result["functions"] if f["name"] == "compute")
        assert compute["is_method"] is True

    def test_route_detected(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        get_item = next(f for f in result["functions"] if f["name"] == "get_item")
        assert get_item["is_route"] is True
        assert get_item["http_method"] == "GET"
        assert "/items/" in get_item["path"]
        assert get_item["status_code"] == 200

    def test_post_route_detected(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        create_item = next(f for f in result["functions"] if f["name"] == "create_item")
        assert create_item["is_route"] is True
        assert create_item["http_method"] == "POST"
        assert create_item["status_code"] == 201

    def test_imports_extracted(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        modules = {imp["module"] for imp in result["imports"]}
        assert "os" in modules
        assert "fastapi" in modules

    def test_module_prefix_applied(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source, module_prefix="mypackage")
        assert result["file"]["module_path"].startswith("mypackage")

    def test_relationships_extracted(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        rel_types = {r["rel"] for r in result["relationships"]}
        assert "INHERITS_FROM" in rel_types or "HAS_METHOD" in rel_types

    def test_source_captured_in_function(self, sample_python_source: str) -> None:
        result = self._write_and_parse(sample_python_source)
        compute = next(f for f in result["functions"] if f["name"] == "compute")
        assert "return" in compute["source"]

    def test_syntax_error_raises_parse_error(self) -> None:
        from codegraph_shared.exceptions import ParseError

        with pytest.raises(ParseError):
            self._write_and_parse("def broken(:\n    pass")

    def test_empty_file(self) -> None:
        result = self._write_and_parse("")
        assert result["classes"] == []
        assert result["functions"] == []
        assert result["imports"] == []


class TestPathToModule:
    """Tests for the _path_to_module helper."""

    def test_simple_file(self) -> None:
        assert _path_to_module("fastapi/routing.py", "fastapi") == "fastapi.routing"

    def test_init_file(self) -> None:
        assert _path_to_module("fastapi/__init__.py", "fastapi") == "fastapi"

    def test_nested_file(self) -> None:
        assert _path_to_module("fastapi/dependencies/utils.py", "fastapi") == "fastapi.dependencies.utils"

    def test_no_prefix(self) -> None:
        assert _path_to_module("routing.py", "") == "routing"
