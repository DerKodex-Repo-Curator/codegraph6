"""Python AST parser that extracts code entities for the knowledge graph.

Uses the stdlib ``ast`` module (no external dependencies) to extract:
- Module-level imports
- Class definitions (with bases, decorators, docstrings)
- Function / method definitions (with signatures, decorators, docstrings)
- FastAPI route handlers (detected via decorator pattern)

All extracted entities are returned as plain dicts matching the Neo4j
node schemas defined in ``codegraph_shared.models``.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Any

from codegraph_shared.exceptions import ParseError
from codegraph_shared.logging import get_logger

logger = get_logger(__name__)

# Decorators that signal a FastAPI route registration.
_ROUTE_DECORATORS = frozenset(
    {
        "get", "post", "put", "patch", "delete", "head", "options", "trace",
        "api_route",
    }
)

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})


def parse_file(
    file_path: Path,
    repo_root: Path,
    module_prefix: str = "",
) -> dict[str, Any]:
    """Parse a Python file and return extracted entities.

    Args:
        file_path: Absolute path to the ``.py`` file.
        repo_root: Repository root (used to compute relative paths).
        module_prefix: Dot-separated prefix for qualified names
            (e.g. ``"fastapi"``).

    Returns:
        Dict with keys ``file``, ``classes``, ``functions``, ``imports``,
        ``relationships``.

    Raises:
        ParseError: If the file cannot be parsed as Python.
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        raise ParseError(str(file_path), exc) from exc

    rel_path = str(file_path.relative_to(repo_root))
    module_path = _path_to_module(rel_path, module_prefix)

    visitor = EntityVisitor(source=source, module_path=module_path)
    visitor.visit(tree)

    lines = source.splitlines()

    return {
        "file": {
            "path": rel_path,
            "module_path": module_path,
            "loc": len(lines),
            "language": "python",
        },
        "classes": visitor.classes,
        "functions": visitor.functions,
        "imports": visitor.imports,
        "relationships": visitor.relationships,
        "parameters": visitor.parameters,
        "decorator_nodes": visitor.decorator_nodes,
        "docstring_nodes": visitor.docstring_nodes,
    }


# ---------------------------------------------------------------------------
# Internal AST visitor
# ---------------------------------------------------------------------------


class EntityVisitor(ast.NodeVisitor):
    """Traverses the AST and collects entities."""

    def __init__(self, source: str, module_path: str) -> None:
        self._source = source
        self._source_lines = source.splitlines()
        self._module_path = module_path
        self._class_stack: list[str] = []
        self._seen_decorators: set[str] = set()

        self.classes: list[dict[str, Any]] = []
        self.functions: list[dict[str, Any]] = []
        self.imports: list[dict[str, Any]] = []
        self.relationships: list[dict[str, str]] = []
        self.parameters: list[dict[str, Any]] = []
        self.decorator_nodes: list[dict[str, Any]] = []
        self.docstring_nodes: list[dict[str, Any]] = []

    # --- Import statements -------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            entry = {
                "module": alias.name,
                "name": "",
                "alias": alias.asname or "",
            }
            entry["id"] = f"{self._module_path}::{alias.name}::"
            self.imports.append(entry)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        for alias in node.names:
            entry = {
                "module": module,
                "name": alias.name,
                "alias": alias.asname or "",
            }
            entry["id"] = f"{self._module_path}::{module}::{alias.name}"
            self.imports.append(entry)
        self.generic_visit(node)

    # --- Class definitions -------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        qname = self._qualified_name(node.name)
        bases = [_unparse_name(b) for b in node.bases]
        decorators = [_unparse_name(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node) or ""

        cls = {
            "qualified_name": qname,
            "name": node.name,
            "bases": bases,
            "is_abstract": _is_abstract(node),
            "decorators": decorators,
            "docstring": docstring,
            "start_line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
        }
        self.classes.append(cls)

        # Decorator nodes (deduplicated globally across the file).
        for dec_name in decorators:
            if dec_name not in self._seen_decorators:
                self.decorator_nodes.append({"name": dec_name})
                self._seen_decorators.add(dec_name)
            self.relationships.append({
                "from": qname, "rel": "DECORATED_BY", "to_decorator": dec_name
            })

        # Docstring node.
        if docstring:
            self.docstring_nodes.append({
                "qualified_name": qname,
                "text": docstring,
                "entity_type": "class",
            })

        # Record INHERITS_FROM relationships for resolved bases.
        for base in bases:
            self.relationships.append({
                "from": qname,
                "rel": "INHERITS_FROM",
                "to": base,
            })

        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    # --- Function definitions ----------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._process_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._process_function(node)

    def _process_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        qname = self._qualified_name(node.name)
        decorators = [_unparse_name(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node) or ""
        is_method = bool(self._class_stack)
        is_async = isinstance(node, ast.AsyncFunctionDef)
        signature = _render_signature(node)
        source = self._extract_source(node)

        # Detect FastAPI route handlers.
        route_info = _detect_route(node)

        func: dict[str, Any] = {
            "qualified_name": qname,
            "name": node.name,
            "is_async": is_async,
            "is_method": is_method,
            "decorators": decorators,
            "signature": signature,
            "docstring": docstring,
            "source": source,
            "start_line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
            "is_route": route_info is not None,
            **(route_info or {}),
        }
        self.functions.append(func)

        # Parameter nodes.
        self.parameters.extend(_extract_parameters(node, qname))

        # Decorator nodes (deduplicated globally across the file).
        for dec_name in decorators:
            if dec_name not in self._seen_decorators:
                self.decorator_nodes.append({"name": dec_name})
                self._seen_decorators.add(dec_name)
            self.relationships.append({
                "from": qname, "rel": "DECORATED_BY", "to_decorator": dec_name
            })

        # Docstring node.
        if docstring:
            self.docstring_nodes.append({
                "qualified_name": qname,
                "text": docstring,
                "entity_type": "function",
            })

        # Record class membership.
        if is_method and self._class_stack:
            class_qname = self._module_path + "." + self._class_stack[-1]
            self.relationships.append({
                "from": class_qname,
                "rel": "HAS_METHOD",
                "to": qname,
            })

        self.generic_visit(node)

    # --- Helpers -----------------------------------------------------------

    def _qualified_name(self, name: str) -> str:
        parts = [self._module_path] + self._class_stack + [name]
        return ".".join(parts)

    def _extract_source(self, node: ast.AST) -> str:
        start = getattr(node, "lineno", 1) - 1
        end = getattr(node, "end_lineno", start + 1)
        lines = self._source_lines[start:end]
        return textwrap.dedent("\n".join(lines))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _path_to_module(rel_path: str, prefix: str) -> str:
    """Convert a relative file path to a dotted module name."""
    path = rel_path.replace("/", ".").replace("\\", ".")
    if path.endswith(".__init__.py"):
        path = path[: -len(".__init__.py")]
    elif path.endswith(".py"):
        path = path[:-3]
    if prefix:
        # Only prepend if not already present.
        if not path.startswith(prefix):
            path = f"{prefix}.{path}" if path else prefix
    return path


def _unparse_name(node: ast.expr) -> str:
    """Safely unparse an expression node to a string."""
    try:
        return ast.unparse(node)
    except Exception:
        return repr(node)


def _is_abstract(node: ast.ClassDef) -> bool:
    """Heuristic: class is abstract if it inherits from ABC or has abstractmethod."""
    bases = {_unparse_name(b) for b in node.bases}
    if "ABC" in bases or "abc.ABC" in bases:
        return True
    for child in ast.walk(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            for dec in child.decorator_list:
                if _unparse_name(dec) in {"abstractmethod", "abc.abstractmethod"}:
                    return True
    return False


def _render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render the parameter list as a string, e.g. ``(self, x: int = 0)``."""
    try:
        return ast.unparse(node.args)
    except Exception:
        return ""


def _detect_route(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, Any] | None:
    """Return route metadata if the function is decorated as a FastAPI route.

    Looks for patterns like ``@router.get("/path")`` or ``@app.post("/path")``.
    """
    for decorator in node.decorator_list:
        # Handle ``@router.get(...)`` or ``@app.post(...)``
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        method_name: str | None = None

        if isinstance(func, ast.Attribute):
            method_name = func.attr.lower()
        elif isinstance(func, ast.Name):
            method_name = func.id.lower()

        if method_name not in _ROUTE_DECORATORS:
            continue

        # Extract the path argument (first positional or ``path`` keyword).
        path = ""
        if decorator.args:
            first_arg = decorator.args[0]
            if isinstance(first_arg, ast.Constant):
                path = str(first_arg.value)
        for kw in decorator.keywords:
            if kw.arg == "path" and isinstance(kw.value, ast.Constant):
                path = str(kw.value.value)

        http_method = method_name if method_name in _HTTP_METHODS else "api_route"

        return {
            "http_method": http_method.upper(),
            "path": path,
            "response_model": _kw_str(decorator, "response_model"),
            "status_code": _kw_int(decorator, "status_code", 200),
            "tags": _kw_list(decorator, "tags"),
        }
    return None


def _kw_str(call: ast.Call, name: str) -> str:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return ""


def _kw_int(call: ast.Call, name: str, default: int) -> int:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            try:
                return int(kw.value.value)
            except (TypeError, ValueError):
                pass
    return default


def _extract_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    func_qname: str,
) -> list[dict[str, Any]]:
    """Extract each parameter of a function as a structured dict.

    Args:
        node: The function AST node.
        func_qname: Qualified name of the parent function.

    Returns:
        List of parameter dicts with ``qualified_name``, ``name``,
        ``type_annotation``, ``kind``, and ``function_qname``.
    """
    params: list[dict[str, Any]] = []
    args = node.args

    def _ann(arg: ast.arg) -> str:
        return ast.unparse(arg.annotation) if arg.annotation else ""

    for arg in args.args:
        params.append({
            "qualified_name": f"{func_qname}.{arg.arg}",
            "name": arg.arg,
            "type_annotation": _ann(arg),
            "kind": "positional_or_keyword",
            "function_qname": func_qname,
        })
    if args.vararg:
        params.append({
            "qualified_name": f"{func_qname}.{args.vararg.arg}",
            "name": args.vararg.arg,
            "type_annotation": _ann(args.vararg),
            "kind": "var_positional",
            "function_qname": func_qname,
        })
    for arg in args.kwonlyargs:
        params.append({
            "qualified_name": f"{func_qname}.{arg.arg}",
            "name": arg.arg,
            "type_annotation": _ann(arg),
            "kind": "keyword_only",
            "function_qname": func_qname,
        })
    if args.kwarg:
        params.append({
            "qualified_name": f"{func_qname}.{args.kwarg.arg}",
            "name": args.kwarg.arg,
            "type_annotation": _ann(args.kwarg),
            "kind": "var_keyword",
            "function_qname": func_qname,
        })
    return params


def _kw_list(call: ast.Call, name: str) -> list[str]:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.List):
            return [
                str(elt.value)
                for elt in kw.value.elts
                if isinstance(elt, ast.Constant)
            ]
    return []
