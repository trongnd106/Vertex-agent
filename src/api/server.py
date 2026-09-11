"""FastAPI server for agent communication — invoke, stream, state, health.

Endpoints:
- ``POST /invoke`` — synchronous agent invocation
- ``POST /stream`` — streaming agent response (SSE)
- ``GET /state/{thread_id}`` — get thread checkpoint state
- ``POST /state/{thread_id}`` — update thread state (interrupt resume)
- ``GET /health`` — health check
- ``GET /metrics`` — runtime metrics
- ``GET /conversations`` — list conversations for a user
- ``DELETE /conversations/{thread_id}`` — delete a conversation
- ``PATCH /conversations/{thread_id}`` — update conversation metadata (title)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.config import config
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.api.rate_limit import RateLimiter
from src.memory.memory_backend import UserContext

logger = logging.getLogger(__name__)


# ── In-memory conversation store ─────────────────────────


@dataclass
class ConversationRecord:
    """A conversation / thread record."""
    thread_id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    messages: list[dict] = field(default_factory=list)


class ConversationStore:
    """Thread-safe in-memory store for conversation metadata.

    Falls back to in-memory when no Postgres is available.
    Later this can be backed by the LangGraph checkpointer.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conversations: dict[str, ConversationRecord] = {}

    def upsert(self, record: ConversationRecord) -> None:
        with self._lock:
            existing = self._conversations.get(record.thread_id)
            if existing:
                existing.title = record.title
                existing.updated_at = record.updated_at
                existing.message_count = max(existing.message_count, record.message_count)
                # Append new messages — deduplicate by content + role to avoid dupes
                seen = set()
                for m in existing.messages:
                    seen.add((m.get("role", ""), m.get("content", "")))
                for m in record.messages:
                    key = (m.get("role", ""), m.get("content", ""))
                    if key not in seen:
                        existing.messages.append(m)
                        seen.add(key)
            else:
                self._conversations[record.thread_id] = record

    def list_by_user(self, user_id: str) -> list[ConversationRecord]:
        with self._lock:
            convs = [c for c in self._conversations.values() if c.user_id == user_id]
            convs.sort(key=lambda c: c.updated_at, reverse=True)
            return convs

    def get(self, thread_id: str) -> ConversationRecord | None:
        with self._lock:
            return self._conversations.get(thread_id)

    def delete(self, thread_id: str) -> bool:
        with self._lock:
            if thread_id in self._conversations:
                del self._conversations[thread_id]
                return True
            return False


# ── Pydantic models ───────────────────────────────────────────────────


class InvokeRequest(BaseModel):
    """Request body for synchronous agent invocation."""
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = ""
    user_id: str = "anonymous"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamRequest(BaseModel):
    """Request body for streaming agent invocation."""
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = ""
    user_id: str = "anonymous"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateUpdateRequest(BaseModel):
    """Request body for updating thread state."""
    values: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error response format."""
    error: str
    detail: str = ""
    error_id: str = ""


# ── Server state ──────────────────────────────────────────────────────


@dataclass
class ServerState:
    """Shared server state accessible from endpoints."""
    started_at: float = 0.0
    total_requests: int = 0
    rate_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(capacity=60, refill_rate=1.0))
    graph: Any = None


server_state = ServerState()

#: Global conversation metadata store (in-memory, ephemeral).
conversation_store = ConversationStore()


# ── Lifespan ──────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize resources on startup."""
    logger.info("Initializing agent server...")
    server_state.started_at = time.time()

    # Import the compiled graph (lazy, so server.py doesn't need LLM keys at import)
    try:
        import importlib
        mod = importlib.import_module("src.agent.server")
        graph = getattr(mod, "graph", None)
        if graph is not None:
            server_state.graph = graph
            logger.info("Agent graph loaded successfully (%s)", type(graph).__name__)
        else:
            logger.warning("Agent server module has no 'graph' attribute")
    except Exception as exc:
        logger.warning("Agent graph not available at startup: %s", exc)
        server_state.graph = None

    yield

    logger.info("Shutting down agent server...")


# ── App factory ───────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance.
    """
    app = FastAPI(
        title="Vertex Agent API",
        version="0.4.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    cors_origins = config.CORS_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins.split(",") if cors_origins != "*" else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Middleware: request ID + timing ────────────────────────────────

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.time()
        response = await call_next(request)
        elapsed = (time.time() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Request-Time-Ms"] = str(round(elapsed, 1))
        server_state.total_requests += 1
        return response

    # ── Middleware: authentication ──────────────────────────────────────

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        # Simple API key check if AUTH_TOKEN is set
        auth_token = config.AUTH_TOKEN
        if auth_token:
            provided = request.headers.get("Authorization", "").removeprefix("Bearer ")
            if provided != auth_token:
                # Allow /health to be public
                if request.url.path != "/health":
                    return JSONResponse(
                        status_code=401,
                        content={"error": "Unauthorized", "detail": "Invalid or missing API key"},
                    )
        return await call_next(request)

    # ── Rate limiting helper ──────────────────────────────────────────

    def check_rate_limit(user_id: str) -> None:
        allowed, _ = server_state.rate_limiter.allow(user_id)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "detail": f"User '{user_id}' has exceeded the rate limit. Try again later.",
                },
            )

    # ── Endpoints ──────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        graph_ok = server_state.graph is not None
        uptime = time.time() - server_state.started_at if server_state.started_at else 0
        status = "ok" if graph_ok else "degraded"
        return {
            "status": status,
            "version": "0.4.0",
            "uptime_seconds": round(uptime, 1),
            "total_requests": server_state.total_requests,
            "graph_loaded": graph_ok,
        }

    @app.get("/metrics")
    async def metrics():
        """Runtime metrics endpoint."""
        return {
            "uptime_seconds": round(time.time() - server_state.started_at, 1) if server_state.started_at else 0,
            "total_requests": server_state.total_requests,
        }

    @app.post("/invoke")
    async def invoke(request: InvokeRequest):
        """Synchronous agent invocation.

        Sends a message to the agent and returns the full response.
        """
        check_rate_limit(request.user_id)

        if server_state.graph is None:
            raise HTTPException(status_code=503, detail="Agent graph not loaded")

        # Prepare input state
        input_state = {
            "messages": [{"role": "user", "content": request.message}],
            "metadata": request.metadata,
        }

        try:
            result = await server_state.graph.ainvoke(
                input_state,
                {"configurable": {"thread_id": request.thread_id}},
                context=UserContext(user_id=request.user_id),
            )
            messages = result.get("messages", [])
            last_message = messages[-1] if messages else {}
            # AIMessage objects → dict
            last_content = last_message.content if hasattr(last_message, "content") else last_message.get("content", "")
            def _role(msg: Any) -> str:
                """Map message type to 'user' | 'assistant'."""
                if hasattr(msg, "type"):
                    t = msg.type
                elif isinstance(msg, dict):
                    t = msg.get("type", "")
                else:
                    t = ""
                return {"human": "user", "ai": "assistant", "user": "user", "assistant": "assistant"}.get(t, t or "user")

            messages_out = []
            for m in messages:
                role = _role(m)
                # Filter out internal messages (tool calls, skill loading, thinking)
                if role == "tool":
                    continue
                content = m.content if hasattr(m, "content") else (m.get("content", "") if isinstance(m, dict) else "")
                messages_out.append({"role": role, "content": content})

            # Deduplicate sequential assistant messages — keep only the last one
            # (internal thinking like "I'll read the skill" → final response)
            filtered = []
            i = 0
            while i < len(messages_out):
                if messages_out[i]["role"] == "assistant":
                    # Find the last consecutive assistant message
                    last_assistant = i
                    while last_assistant + 1 < len(messages_out) and messages_out[last_assistant + 1]["role"] == "assistant":
                        last_assistant += 1
                    # Keep only the last assistant message in a sequence
                    filtered.append(messages_out[last_assistant])
                    i = last_assistant + 1
                else:
                    filtered.append(messages_out[i])
                    i += 1
            messages_out = filtered

            # Auto-save conversation messages + metadata
            title = request.message[:40] + ("..." if len(request.message) > 40 else "")
            conversation_store.upsert(ConversationRecord(
                thread_id=request.thread_id,
                user_id=request.user_id,
                title=title,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                message_count=len(messages) // 2,  # approx turns
                messages=messages_out,
            ))

            return {
                "thread_id": request.thread_id,
                "response": last_content,
                "messages": messages_out,
            }
        except Exception as exc:
            logger.error("Invoke failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/stream")
    async def stream(request: StreamRequest):
        """Streaming agent invocation (SSE).

        Sends a message and streams the response as server-sent events.
        """
        check_rate_limit(request.user_id)

        if server_state.graph is None:
            raise HTTPException(status_code=503, detail="Agent graph not loaded")

        input_state = {
            "messages": [{"role": "user", "content": request.message}],
            "metadata": request.metadata,
        }

        async def event_stream():
            try:
                async for event in server_state.graph.astream_events(
                    input_state,
                    {"configurable": {"thread_id": request.thread_id}},
                    context=UserContext(user_id=request.user_id),
                    version="v2",
                ):
                    event_type = event.get("event", "")
                    data = json.dumps(event, default=str)
                    yield f"event: {event_type}\ndata: {data}\n\n"
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/state/{thread_id}")
    async def get_state(thread_id: str):
        """Get thread checkpoint state."""
        if server_state.graph is None:
            raise HTTPException(status_code=503, detail="Agent graph not loaded")

        try:
            state = await server_state.graph.aget_state({"configurable": {"thread_id": thread_id}})
            if state is None:
                raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found")
            return {
                "thread_id": thread_id,
                "values": state.values if hasattr(state, "values") else {},
                "next": state.next if hasattr(state, "next") else [],
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/state/{thread_id}")
    async def update_state(thread_id: str, request: StateUpdateRequest):
        """Update thread state (e.g. resume from interrupt)."""
        if server_state.graph is None:
            raise HTTPException(status_code=503, detail="Agent graph not loaded")

        try:
            await server_state.graph.aupdate_state(
                {"configurable": {"thread_id": thread_id}},
                request.values,
            )
            return {"thread_id": thread_id, "status": "updated"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Conversation (history) endpoints ─────────────────────────────────

    @app.get("/conversations")
    async def list_conversations(user_id: str = Query("anonymous")):
        """List all conversations for a user, newest first."""
        convs = conversation_store.list_by_user(user_id)
        return [
            {
                "thread_id": c.thread_id,
                "title": c.title,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "message_count": c.message_count,
            }
            for c in convs
        ]

    @app.get("/conversations/{thread_id}")
    async def get_conversation(thread_id: str):
        """Get conversation details including messages."""
        record = conversation_store.get(thread_id)
        if not record:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {
            "thread_id": record.thread_id,
            "title": record.title,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "message_count": record.message_count,
            "messages": record.messages,
        }

    @app.delete("/conversations/{thread_id}")
    async def delete_conversation(thread_id: str):
        """Delete a conversation record."""
        if conversation_store.delete(thread_id):
            return {"status": "deleted", "thread_id": thread_id}
        # Still return success — record may have already been cleaned up
        return {"status": "not_found", "thread_id": thread_id}

    @app.patch("/conversations/{thread_id}")
    async def update_conversation(thread_id: str, request: Request):
        """Update conversation metadata (e.g. rename title)."""
        body = await request.json()
        title = body.get("title", "")
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        record = conversation_store.get(thread_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Conversation '{thread_id}' not found")
        record.title = title
        record.updated_at = datetime.now(timezone.utc)
        conversation_store.upsert(record)
        return {"status": "updated", "thread_id": thread_id}

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        error_id = str(uuid.uuid4())
        logger.error("Unhandled error %s: %s", error_id, exc)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="Internal server error",
                detail=str(exc),
                error_id=error_id,
            ).model_dump(),
        )

    return app


# ── Entrypoint ────────────────────────────────────────────────────────


app = create_app()


if __name__ == "__main__":
    import uvicorn

    host = config.SERVER_HOST
    port = config.SERVER_PORT
    uvicorn.run(app, host=host, port=port, log_level="info")