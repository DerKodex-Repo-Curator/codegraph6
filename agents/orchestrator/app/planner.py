"""LLM-driven planning and tool-use loop for the Orchestrator.

The Planner runs a standard Anthropic tool-use loop. It discovers tools
dynamically from the AgentRegistry at startup, so it automatically picks up
new capabilities when child agents are updated.

Flow per request:
1. Load conversation history from Redis.
2. Send history + question to Claude with all child-agent tools available.
3. Execute tool calls against the appropriate child agent.
4. Repeat until Claude produces a final text response.
5. Save updated history to Redis.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from codegraph_shared.logging import get_logger
from codegraph_shared.mcp_client import AgentRegistry, call_agent_tool

from .memory import ConversationMemory

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are an expert code assistant with access to a knowledge graph of indexed Python repositories. \
You answer questions by querying the graph and analyzing code — never by guessing or fabricating.

## Knowledge Graph Schema

Nodes and their key properties:
- File        — path, module_path, loc
- Class       — qualified_name, name, bases, docstring
- Function    — qualified_name, name, is_async, is_method, signature, docstring, source
- Route       — (extends Function) http_method, path, tags

Relationships:
- (File)-[:DEFINES]->(Class|Function)
- (File)-[:IMPORTS]->(File)
- (Class)-[:INHERITS_FROM]->(Class)
- (Class)-[:HAS_METHOD]->(Function)
- (Function)-[:CALLS]->(Function)

Qualified name format: `package.module.ClassName.method_name`
Examples: `fastapi.applications.FastAPI`, `fastapi.routing.APIRouter.add_api_route`

## Tool Categories

**Graph tools** — use these first to locate entities and relationships:
- `find_entity(name, kind, limit)` — find a Class or Function by name (case-insensitive substring match)
- `get_dependencies(qualified_name, depth)` — what this entity imports or calls
- `execute_query(cypher, params)` — run a custom read-only Cypher query
- `natural_language_query(question)` — convert a plain-English question to Cypher and run it
- `graph_statistics()` — counts of nodes by label; call this if you're unsure what's indexed

**Code analysis tools** — use these after locating entities in the graph:
- `analyze_function(qualified_name, focus)` — deep analysis of a function's logic and patterns
- `analyze_class(qualified_name)` — class structure, inheritance, and responsibilities
- `explain_implementation(qualified_name)` — how an entity works end-to-end

**Indexer tools** — only when the user explicitly asks to index a repository:
- `index_repository(repository_url, force)` — clone and index a repo into the graph
- `get_index_status(job_id)` — poll indexing progress

## Reasoning Strategy

**Simple questions** (find a class, show a docstring):
1. `find_entity` → return the result directly.

**Medium questions** (how does X work, what inherits from Y):
1. `find_entity` to locate the entity's qualified_name.
2. `analyze_function` or `analyze_class` for explanation.

**Complex questions** (lifecycle of a request, compare two implementations, design patterns):
1. `graph_statistics` if unsure what is indexed.
2. `find_entity` or `natural_language_query` for each relevant entity — these can be called in parallel.
3. `analyze_function` / `analyze_class` on the located entities — also parallelisable when independent.
4. Synthesize all results into a single coherent answer.

## Rules

- Always query the graph before answering — do not rely on prior knowledge of the codebase.
- Prefer `find_entity` over `natural_language_query` for simple lookups; it is faster and more precise.
- When a question mentions multiple entities (e.g. "compare Path and Query"), issue graph/analysis \
tool calls for each entity in the same turn rather than sequentially across turns.
- Cite qualified names found in the graph (e.g. `fastapi.routing.APIRouter`) in every answer.
- If an entity is not found in the graph, say so explicitly — do not fabricate code or relationships.
- Never call indexer tools unless the user's message explicitly asks to index a repository.
"""


class Planner:
    """Executes the multi-agent tool-use loop for a single query.

    Args:
        anthropic_client: Configured Anthropic async client.
        registry: AgentRegistry with live child-agent sessions.
        memory: Conversation memory manager.
        model: Claude model to use.
        max_tokens: Token limit for each LLM call.
    """

    def __init__(
        self,
        anthropic_client: anthropic.AsyncAnthropic,
        registry: AgentRegistry,
        memory: ConversationMemory,
        *,
        model: str,
        max_tokens: int = 8192,
    ) -> None:
        self._client = anthropic_client
        self._registry = registry
        self._memory = memory
        self._model = model
        self._max_tokens = max_tokens

    async def run(
        self,
        session_id: str,
        question: str,
    ) -> str:
        """Answer *question* using multi-agent collaboration.

        Args:
            session_id: Identifies the conversation for history retrieval.
            question: The user's question.

        Returns:
            The assistant's final text response.
        """
        # Load history.
        history = await self._memory.load_history(session_id)

        # Build messages for this turn.
        new_user_msg: dict[str, Any] = {"role": "user", "content": question}
        messages = history + [new_user_msg]

        # Get all tools from child agents.
        tools = self._registry.all_anthropic_tools()

        # Track the new messages produced this turn (to save to history).
        turn_messages: list[dict[str, Any]] = [new_user_msg]

        final_text = ""
        max_iterations = 10  # Safety cap to prevent infinite loops.

        for iteration in range(max_iterations):
            logger.debug(
                "planner_iteration",
                session_id=session_id,
                iteration=iteration,
                message_count=len(messages),
            )

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )

            # Build the assistant message for the next turn.
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
            }
            messages.append(assistant_msg)
            turn_messages.append({"role": "assistant", "content": _serialize_content(response.content)})

            if response.stop_reason == "end_turn":
                # Collect all text blocks.
                text_parts = [
                    block.text
                    for block in response.content
                    if hasattr(block, "text")
                ]
                final_text = "\n".join(text_parts)
                break

            if response.stop_reason != "tool_use":
                # Unexpected stop reason; return whatever text we have.
                text_parts = [
                    block.text
                    for block in response.content
                    if hasattr(block, "text")
                ]
                final_text = "\n".join(text_parts) or "I encountered an unexpected issue."
                break

            # Execute all tool calls.
            tool_results = await self._execute_tool_calls(response.content)

            # Append tool results to messages.
            tool_result_msg: dict[str, Any] = {
                "role": "user",
                "content": tool_results,
            }
            messages.append(tool_result_msg)
            turn_messages.append(tool_result_msg)

        else:
            logger.warning("planner_max_iterations", session_id=session_id)
            final_text = "I reached the maximum number of reasoning steps. Please try a more specific question."

        # Save updated history.
        await self._memory.append_messages(session_id, turn_messages)

        return final_text

    async def _execute_tool_calls(
        self, content_blocks: list[Any]
    ) -> list[dict[str, Any]]:
        """Execute all tool_use blocks and return tool_result messages."""
        results = []
        for block in content_blocks:
            if not hasattr(block, "type") or block.type != "tool_use":
                continue

            tool_name: str = block.name
            tool_input: dict[str, Any] = block.input
            tool_use_id: str = block.id

            logger.info(
                "executing_tool",
                tool=tool_name,
                tool_use_id=tool_use_id,
            )

            try:
                agent_name = self._registry.find_agent_for_tool(tool_name)
                session = self._registry.get_session(agent_name)
                result = await call_agent_tool(session, tool_name, tool_input)
                result_text = json.dumps(result) if not isinstance(result, str) else result
                is_error = False
            except Exception as exc:
                logger.error("tool_call_failed", tool=tool_name, error=str(exc))
                result_text = f"Tool call failed: {exc}"
                is_error = True

            results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result_text,
                "is_error": is_error,
            })

        return results


def _serialize_content(content_blocks: list[Any]) -> list[dict[str, Any]]:
    """Convert Anthropic SDK content blocks to JSON-serialisable dicts."""
    serialized = []
    for block in content_blocks:
        if hasattr(block, "type"):
            if block.type == "text":
                serialized.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                serialized.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
    return serialized
