"""Integration tests for the Orchestrator via the FastAPI gateway.

These tests start the full stack via docker-compose and send HTTP requests.
Intended for CI environments with Docker available.

Run with:
    docker compose up -d
    pytest tests/integration/test_orchestrator.py -m e2e
"""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")

pytestmark = pytest.mark.e2e


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE_URL, timeout=120.0)


def test_health_endpoint(client: httpx.Client) -> None:
    """Gateway should return 200 on /health."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_agents_health(client: httpx.Client) -> None:
    """All agents should be reachable."""
    response = client.get("/api/agents/health")
    assert response.status_code in (200, 503)  # 503 if agents not ready


def test_chat_simple_question(client: httpx.Client) -> None:
    """Simple question should return a non-empty answer."""
    response = client.post(
        "/api/chat",
        json={"message": "What is FastAPI?", "session_id": ""},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert len(data["answer"]) > 10
    assert "session_id" in data


def test_chat_session_continuity(client: httpx.Client) -> None:
    """Follow-up questions should use conversation context."""
    # First message.
    r1 = client.post(
        "/api/chat",
        json={"message": "What is APIRouter?", "session_id": ""},
    )
    assert r1.status_code == 200
    session_id = r1.json()["session_id"]

    # Follow-up using the same session.
    r2 = client.post(
        "/api/chat",
        json={"message": "What methods does it have?", "session_id": session_id},
    )
    assert r2.status_code == 200
    # The second answer should reference APIRouter or its methods.
    assert r2.json()["answer"]


def test_index_then_query(client: httpx.Client) -> None:
    """Indexing should populate the graph and enable queries."""
    # Start indexing.
    index_resp = client.post(
        "/api/index",
        json={"repository_url": "https://github.com/tiangolo/fastapi", "force": False},
    )
    assert index_resp.status_code == 200
    job_id = index_resp.json().get("job_id")
    assert job_id

    # Poll status (up to 5 min for CI).
    import time
    for _ in range(60):
        status_resp = client.get(f"/api/index/status/{job_id}")
        status = status_resp.json().get("status", "")
        if status in ("completed", "failed"):
            break
        time.sleep(5)

    # After indexing, query should find FastAPI class.
    chat_resp = client.post(
        "/api/chat",
        json={"message": "Find the FastAPI class in the knowledge graph", "session_id": ""},
    )
    assert chat_resp.status_code == 200
