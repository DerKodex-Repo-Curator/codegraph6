"""Natural language to Cypher query builder with safety validation.

The LLM is given the graph schema and instructed to produce a JSON payload
containing a parameterised Cypher query and its parameter dict.  The raw
query string is then validated to ensure it contains no write clauses before
being executed against Neo4j.
"""

from __future__ import annotations

import json
import re

import anthropic

from codegraph_shared.exceptions import UnsafeCypherError
from codegraph_shared.logging import get_logger

logger = get_logger(__name__)

# Pattern for Cypher write operations that must be rejected.
_WRITE_CLAUSE_RE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH\s+DELETE|SET\s+\w|REMOVE|DROP|LOAD\s+CSV"
    r"|CALL\s+apoc\.schema|CALL\s+db\.schema\.nodeTypeProperties)\b",
    re.IGNORECASE,
)

_SCHEMA_SUMMARY = """
Available node labels and key properties:
- Repository {url, name, commit_sha}
- File {path, module_path, loc}
- Class {qualified_name, name, bases, is_abstract, docstring}
- Function {qualified_name, name, is_async, is_method, decorators, signature, docstring, source}
- Route:Function {http_method, path, response_model, status_code, tags}

Relationship types:
- (:Repository)-[:CONTAINS]->(:File)
- (:File)-[:DEFINES]->(:Class | :Function)
- (:Class)-[:INHERITS_FROM]->(:Class)
- (:Class)-[:HAS_METHOD]->(:Function)
- (:File)-[:IMPORTS]->(:File)
- (:Function)-[:CALLS]->(:Function)

Full-text index: entity_search on Class/Function/File (name, docstring).
"""

_SYSTEM_PROMPT = f"""You are a Neo4j Cypher expert. Convert user questions about a Python codebase into Cypher queries.

{_SCHEMA_SUMMARY}

RULES:
1. Output ONLY valid JSON with keys "query" (string) and "params" (object).
2. Never include CREATE, MERGE, DELETE, SET, REMOVE, DROP, or LOAD CSV.
3. Always LIMIT results. Default to LIMIT 20 unless the user asks for more.
4. Use OPTIONAL MATCH where relationships might be absent.
5. Use parameterised queries — never interpolate values directly into Cypher.
6. For name lookups, use case-insensitive matching: WHERE toLower(n.name) = toLower($name).

Example output:
{{"query": "MATCH (c:Class) WHERE toLower(c.name) = toLower($name) RETURN c LIMIT 1", "params": {{"name": "APIRouter"}}}}
"""


class QueryBuilder:
    """Converts natural language questions to validated Cypher queries.

    Args:
        api_key: Anthropic API key.
        model: Claude model identifier to use for query generation.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def build(self, question: str) -> tuple[str, dict]:
        """Generate and validate a Cypher query for *question*.

        Args:
            question: Natural language question about the codebase.

        Returns:
            Tuple of (cypher_query, params_dict).

        Raises:
            UnsafeCypherError: If the generated query contains write clauses.
            ValueError: If the LLM output cannot be parsed as JSON.
        """
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown code fences if the model added them.
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return valid JSON: {raw[:300]}") from exc

        query: str = payload.get("query", "")
        params: dict = payload.get("params", {})

        validate_cypher(query)
        logger.debug("cypher_generated", question=question[:100], query=query[:200])
        return query, params


def validate_cypher(query: str) -> str:
    """Raise :class:`UnsafeCypherError` if *query* contains write clauses.

    Args:
        query: Cypher query string to validate.

    Returns:
        The query unchanged (for chaining).
    """
    if _WRITE_CLAUSE_RE.search(query):
        raise UnsafeCypherError(query)
    return query
