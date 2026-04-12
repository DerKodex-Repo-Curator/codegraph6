# CodeGraph – Codebase Intelligence

A production-ready **multi-agent system** that answers questions about any GitHub codebase. Built with the **Model Context Protocol (MCP)**, a **Neo4j** knowledge graph, **Claude**, and a React frontend.

<img width="1470" height="799" alt="codegraph" src="https://github.com/user-attachments/assets/06966d40-9d27-43d3-ac0a-900a4f896159" />
<img width="1470" height="799" alt="codegraph2" src="https://github.com/user-attachments/assets/5fff867d-bbca-4c47-b35d-475a612ecb31" />
<img width="1467" height="792" alt="codegrpah3" src="https://github.com/user-attachments/assets/a0e1583a-c46e-41d6-8159-9f2311030a7a" />

---

## Architecture

```
User
  │
  ▼ HTTP / WebSocket
┌─────────────────────┐
│   FastAPI Gateway   │  ← Public API surface (port 8080)
└──────────┬──────────┘
           │ MCP over SSE
           ▼
┌─────────────────────┐
│   Orchestrator      │  ← Central coordinator (port 8000)
│   (MCP Server +     │    Runs tool-use loop with Claude
│    MCP Client)      │
└──┬────────┬─────────┘
   │        │        │
   │MCP SSE │        │MCP SSE
   ▼        ▼        ▼
┌──────┐ ┌──────┐ ┌──────────────┐
│Index │ │Graph │ │Code Analyst  │
│Agent │ │Query │ │Agent         │
│:8001 │ │:8002 │ │:8003         │
└──┬───┘ └──┬───┘ └──────┬───────┘
   │        │            │
   └────────┼────────────┘
            ▼
      ┌─────────┐   ┌───────┐
      │  Neo4j  │   │ Redis │
      │  :7687  │   │ :6379 │
      └─────────┘   └───────┘
```

### Agent Responsibilities

| Agent | Port | Responsibility |
|---|---|---|
| **Gateway** | 8080 | REST / WebSocket / SSE API, user-facing |
| **Orchestrator** | 8000 | Routing, Claude tool-use loop, synthesis |
| **Indexer** | 8001 | Clone repo, parse AST, write to Neo4j |
| **Graph Query** | 8002 | Cypher queries, NL→Cypher, graph traversal |
| **Code Analyst** | 8003 | Deep code analysis, pattern detection, explanations |

---

## Setup

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose v2
- An [Anthropic API key](https://console.anthropic.com/)
- Node.js 18+ (for the frontend)

---

### 1 — Clone the repository

```bash
git clone https://github.com/your-username/codegraph
cd codegraph
```

---

### 2 — Configure environment

```bash
cp .env.example .env
```

Open `.env` and set:

```env
ANTHROPIC_API_KEY=sk-ant-...
NEO4J_PASSWORD=your-strong-password
```

---

### 3 — Start the backend

```bash
docker compose build --parallel
docker compose up -d
```

Wait ~30 seconds, then verify all agents are healthy:

```bash
curl http://localhost:8080/api/agents/health
```

---

### 4 — Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

---

### 5 — Index a repository

In the UI click **Index repo**, paste a GitHub URL (e.g. `https://github.com/tiangolo/fastapi`), and hit **Index**. Indexing runs in the background and takes 2–5 minutes for a typical repo (~200 files).

Alternatively via curl:

```bash
curl -X POST http://localhost:8080/api/index \
  -H "Content-Type: application/json" \
  -d '{"repository_url": "https://github.com/tiangolo/fastapi"}'
```

---

### 6 — Ask questions

Use the chat UI, or via curl:

```bash
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What design patterns are used in FastAPI?"}'
```

Pass back `session_id` from the first response to maintain conversation history.

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Send a message, get a response |
| `GET` | `/api/chat/stream` | SSE streaming chat |
| `WS` | `/ws/chat` | WebSocket real-time chat |
| `POST` | `/api/index` | Trigger repository indexing |
| `GET` | `/api/index/status/{job_id}` | Poll indexing progress |
| `GET` | `/api/agents/health` | Agent connectivity status |
| `GET` | `/api/graph/statistics` | Knowledge graph node counts |

Full interactive docs: [http://localhost:8080/docs](http://localhost:8080/docs)

---

## Sample Queries

**Simple**
```
What is the FastAPI class?
Show me the docstring for the Depends function
List all routes in fastapi.routing
```

**Medium**
```
How does FastAPI handle request validation?
What classes inherit from APIRouter?
Find all decorators used in the routing module
```

**Complex**
```
Explain the complete lifecycle of a FastAPI request
How does dependency injection work? Show examples from the codebase
What design patterns are used in FastAPI's core and why?
Compare how Path and Query parameters are implemented
```

---

## Knowledge Graph Schema

### Node Labels

| Label | Key Properties |
|---|---|
| `Repository` | `url`, `name`, `commit_sha` |
| `File` | `path`, `module_path`, `loc` |
| `Class` | `qualified_name`, `name`, `bases`, `docstring` |
| `Function` | `qualified_name`, `name`, `is_async`, `source`, `docstring` |
| `Route` | + `http_method`, `path`, `status_code`, `tags` |

### Relationship Types

| Relationship | Meaning |
|---|---|
| `CONTAINS` | Repository → File |
| `DEFINES` | File → Class / Function |
| `INHERITS_FROM` | Class → Class |
| `HAS_METHOD` | Class → Function |
| `CALLS` | Function → Function |
| `IMPORTS` | File → File |

---

## Project Structure

```
codegraph/
├── shared/               # Shared Python package (Neo4j client, settings, exceptions)
│   └── codegraph_shared/
├── agents/
│   ├── orchestrator/     # MCP server + client, Claude tool-use loop
│   ├── indexer/          # AST parser, Neo4j writer
│   ├── graph_query/      # Cypher executor, NL→Cypher
│   └── code_analyst/     # Claude-powered code analysis
├── gateway/              # FastAPI REST / WS / SSE API
├── frontend/             # React + Vite + Tailwind UI
├── infra/                # Neo4j schema, Redis config
├── tests/                # Unit + integration + e2e tests
└── docker-compose.yml
```

---

## Development

```bash
# Run unit tests (no external dependencies needed)
make test-unit

# Open a shell in a service
make shell SVC=orchestrator

# Tail all logs
make logs

# Rebuild after code changes
make build && make up
```

---

## Design Decisions

**Why MCP?** Each agent advertises its own tools over SSE. The Orchestrator discovers them at startup — adding a new agent is as simple as adding its URL to config.

**Why Claude for routing?** The Orchestrator doesn't hardcode rules. It presents all child-agent tools to Claude and lets the model decide the call order. The system adapts to new query types without code changes.

**Why Neo4j?** A property graph maps the relationships between files, classes, functions, and routes naturally. Cypher queries express "find all classes that inherit from X and call Y" in a single statement that would require multiple JOINs in SQL.

**NL→Cypher safety** The Graph Query agent validates every generated Cypher against a regex blocklist before execution, and always passes parameters separately (never interpolated).

---

## Known Limitations

- **Streaming** — the chat endpoint simulates streaming by chunking the completed answer. True token-level streaming through the MCP tool-use chain requires Anthropic SDK changes.
- **Call graph** — `CALLS` relationships only capture static calls within the same file (no inter-procedural analysis).
- **Auth** — the gateway has no authentication layer. Add JWT middleware before any public deployment.

---

## License

MIT
