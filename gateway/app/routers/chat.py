"""Chat API endpoints.

Exposes both a standard JSON POST endpoint and a WebSocket endpoint for
real-time streaming responses.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse

from codegraph_shared.logging import get_logger

from ..schemas.chat import ChatRequest, ChatResponse
from ..services.orchestrator_client import OrchestratorClient

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


def _get_client(request: Request) -> OrchestratorClient:
    return request.app.state.orchestrator


@router.post("/chat", response_model=ChatResponse, summary="Send a chat message")
async def chat(body: ChatRequest, request: Request) -> JSONResponse:
    """Send a message and receive a response from the multi-agent system.

    For streaming responses, set ``stream: true`` and use the SSE endpoint
    or the WebSocket endpoint instead.
    """
    client = _get_client(request)
    session_id = body.session_id or uuid.uuid4().hex

    logger.info("chat_request", session_id=session_id, message_len=len(body.message))

    try:
        result = await client.chat(body.message, session_id=session_id)
        return JSONResponse(
            content={
                "answer": result.get("answer", ""),
                "session_id": result.get("session_id", session_id),
            }
        )
    except Exception as exc:
        logger.error("chat_failed", error=str(exc), session_id=session_id)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "session_id": session_id},
        )


@router.get("/chat/stream", summary="Streaming chat via SSE")
async def chat_stream(
    message: str,
    session_id: str = "",
    request: Request = None,
):
    """Stream a chat response as Server-Sent Events.

    The response consists of ``chunk`` events (partial answer text) and a
    final ``done`` event containing the full answer and session ID.

    Query parameters:
    - **message**: The user's question.
    - **session_id**: Conversation session ID (optional).
    """
    client = _get_client(request)
    sid = session_id or uuid.uuid4().hex

    async def event_generator():
        try:
            # Non-streaming call wrapped to look like SSE.
            # TODO: Replace with actual streaming when Anthropic SDK streaming
            # is plumbed through the MCP tool-use chain.
            yield {"event": "start", "data": json.dumps({"session_id": sid})}
            result = await client.chat(message, session_id=sid)
            answer = result.get("answer", "")

            # Simulate chunked delivery for UX.
            words = answer.split(" ")
            chunk: list[str] = []
            for i, word in enumerate(words):
                chunk.append(word)
                if (i + 1) % 10 == 0:
                    yield {
                        "event": "chunk",
                        "data": json.dumps({"text": " ".join(chunk) + " "}),
                    }
                    chunk = []
                    await asyncio.sleep(0)  # yield control
            if chunk:
                yield {"event": "chunk", "data": json.dumps({"text": " ".join(chunk)})}

            yield {"event": "done", "data": json.dumps({"session_id": sid, "answer": answer})}
        except Exception as exc:
            logger.error("stream_failed", error=str(exc))
            yield {"event": "error", "data": json.dumps({"error": str(exc)})}

    return EventSourceResponse(event_generator())


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for real-time chat.

    Clients send JSON messages: ``{"message": "...", "session_id": "..."}``.
    The server responds with: ``{"answer": "...", "session_id": "..."}``.
    """
    await websocket.accept()
    client: OrchestratorClient = websocket.app.state.orchestrator

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                message = data.get("message", "")
                session_id = data.get("session_id", "") or uuid.uuid4().hex

                if not message:
                    await websocket.send_json({"error": "message is required"})
                    continue

                result = await client.chat(message, session_id=session_id)
                await websocket.send_json({
                    "answer": result.get("answer", ""),
                    "session_id": result.get("session_id", session_id),
                })
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
            except Exception as exc:
                logger.error("websocket_error", error=str(exc))
                await websocket.send_json({"error": str(exc)})
    except WebSocketDisconnect:
        logger.info("websocket_disconnected")
