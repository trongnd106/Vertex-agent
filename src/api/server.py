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
from pathlib import Path

import sqlite3

from src.config import config
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from src.api.rate_limit import RateLimiter
from src.memory.memory_backend import UserContext

logger = logging.getLogger(__name__)


# ── Persistent conversation store (SQLite) ─────────────


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
    """SQLite-backed store for conversation metadata.

    Persists across server restarts so the UI can still list
    conversations after a restart.
    """

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        import sqlite3
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    thread_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    messages TEXT NOT NULL DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_user
                ON conversations(user_id, updated_at DESC)
            """)
            conn.commit()

    def upsert(self, record: ConversationRecord) -> None:
        import sqlite3
        import json
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                existing = conn.execute(
                    "SELECT messages FROM conversations WHERE thread_id = ?",
                    (record.thread_id,),
                ).fetchone()
                if existing:
                    existing_msgs: list[dict] = json.loads(existing[0])
                    seen = set()
                    for m in existing_msgs:
                        seen.add((m.get("role", ""), m.get("content", "")))
                    for m in record.messages:
                        key = (m.get("role", ""), m.get("content", ""))
                        if key not in seen:
                            existing_msgs.append(m)
                            seen.add(key)
                    conn.execute(
                        """UPDATE conversations
                           SET title = ?, updated_at = ?, message_count = ?,
                               messages = ?
                           WHERE thread_id = ?""",
                        (
                            record.title,
                            record.updated_at.isoformat(),
                            max(record.message_count, len(existing_msgs) // 2),
                            json.dumps(existing_msgs, default=str),
                            record.thread_id,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO conversations
                           (thread_id, user_id, title, created_at, updated_at,
                            message_count, messages)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            record.thread_id,
                            record.user_id,
                            record.title,
                            record.created_at.isoformat(),
                            record.updated_at.isoformat(),
                            record.message_count,
                            json.dumps(record.messages, default=str),
                        ),
                    )
                conn.commit()

    def list_by_user(self, user_id: str) -> list[ConversationRecord]:
        import sqlite3
        import json
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    """SELECT thread_id, user_id, title, created_at, updated_at,
                              message_count, messages
                       FROM conversations
                       WHERE user_id = ?
                       ORDER BY updated_at DESC""",
                    (user_id,),
                ).fetchall()
                result: list[ConversationRecord] = []
                for row in rows:
                    result.append(ConversationRecord(
                        thread_id=row[0],
                        user_id=row[1],
                        title=row[2],
                        created_at=datetime.fromisoformat(row[3]),
                        updated_at=datetime.fromisoformat(row[4]),
                        message_count=row[5],
                        messages=json.loads(row[6]),
                    ))
                return result

    def get(self, thread_id: str) -> ConversationRecord | None:
        import sqlite3
        import json
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    """SELECT thread_id, user_id, title, created_at, updated_at,
                              message_count, messages
                       FROM conversations WHERE thread_id = ?""",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    return None
                return ConversationRecord(
                    thread_id=row[0],
                    user_id=row[1],
                    title=row[2],
                    created_at=datetime.fromisoformat(row[3]),
                    updated_at=datetime.fromisoformat(row[4]),
                    message_count=row[5],
                    messages=json.loads(row[6]),
                )

    def delete(self, thread_id: str) -> bool:
        import sqlite3
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cur = conn.execute(
                    "DELETE FROM conversations WHERE thread_id = ?",
                    (thread_id,),
                )
                conn.commit()
                return cur.rowcount > 0


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
    checkpointer: Any = None
    """In-memory checkpointer for persisting thread state across invocations."""
    store: BaseStore | None = None
    """In-memory store for cross-session memory when running standalone."""


server_state = ServerState()

#: Global conversation metadata store (SQLite-backed, created in lifespan).
conversation_store: ConversationStore | None = None


# ── Lifespan ──────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize resources on startup."""
    logger.info("Initializing agent server...")
    server_state.started_at = time.time()

    # ── Create SQLite-backed checkpointer and store ──────────────────────
    # These persist thread state (conversation history) and cross-session
    # memory across server restarts. Stored in .vertex/agent/ in the
    # project root.
    data_dir = Path(__file__).resolve().parent.parent.parent / ".vertex" / "agent"
    data_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = str(data_dir / "checkpoints.sqlite")

    # SqliteSaver — persist thread checkpoints across restarts
    sqlite_conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    sqlite_conn.execute("PRAGMA journal_mode=WAL")
    sqlite_conn.execute("PRAGMA synchronous=NORMAL")
    server_state.checkpointer = SqliteSaver(sqlite_conn)
    # InMemoryStore is ephemeral by nature — switch to SQL-based store if
    # deepagents/long-term memory needs persist across restarts.
    server_state.store = InMemoryStore()
    logger.info("SQLite checkpointer created at %s", sqlite_path)

    # ── Persistent conversation store ────────────────────────────────────
    global conversation_store
    conversation_store = ConversationStore(str(data_dir / "conversations.sqlite"))
    logger.info("Conversation store created at %s", data_dir / "conversations.sqlite")

    # Import the compiled graph (lazy, so server.py doesn't need LLM keys at import)
    try:
        import importlib

        # Rebuild the graph WITH checkpointer + store so it doesn't
        # crash on get_store() / .aget() when running standalone.
        graph_mod = importlib.import_module("src.agent.graph")
        build_fn = getattr(graph_mod, "build_agent")

        # Resolve model the same way src/agent/server.py does
        from src.agent.server import _model_from_env

        model = _model_from_env()
        from src.agent.system_prompt import build_system_prompt

        system_prompt = build_system_prompt(
            model_name=model.split(":", 1)[1] if ":" in model else model,
            provider_name=config.LLM_PROVIDER or "OpenAI",
            show_env_hints=True,
        )

        server_state.graph = build_fn(
            model=model,
            system_prompt=system_prompt,
            checkpointer=server_state.checkpointer,
            store=server_state.store,
        )
        logger.info(
            "Agent graph built with checkpointer + store (%s)",
            type(server_state.graph).__name__,
        )
    except Exception as exc:
        logger.warning("Agent graph build failed (%s); trying pre-compiled graph", exc)
        # Fallback: try the pre-compiled module-level graph (no checkpointer)
        try:
            mod = importlib.import_module("src.agent.server")
            graph = getattr(mod, "graph", None)
            if graph is not None:
                server_state.graph = graph
                logger.info("Fallback: loaded pre-compiled graph (%s)", type(graph).__name__)
            else:
                logger.warning("Fallback: agent server module has no 'graph' attribute")
        except Exception as exc2:
            logger.warning("Fallback also failed: %s", exc2)
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
        The agent sees the full conversation history because:
        1. Previous messages are loaded from the checkpointer (thread state)
        2. The new user message is appended
        """
        check_rate_limit(request.user_id)

        if server_state.graph is None:
            raise HTTPException(status_code=503, detail="Agent graph not loaded")

        # ── Build config for this invocation ─────────────────────────────
        run_config = {"configurable": {"thread_id": request.thread_id}}

        try:
            # ── Load existing thread state for conversation history ──────
            existing_messages: list[dict | Any] = []
            try:
                state = await server_state.graph.aget_state(run_config)
                if state is not None and hasattr(state, "values"):
                    stored = state.values.get("messages", [])
                    if stored:
                        existing_messages = list(stored)
                        logger.debug(
                            "Loaded %d existing messages for thread %s",
                            len(existing_messages),
                            request.thread_id,
                        )
            except Exception as state_err:
                # First call for this thread — no state yet, that's fine
                logger.debug("No existing state for thread %s: %s", request.thread_id, state_err)

            # ── Append new user message ─────────────────────────────────
            new_message: dict | Any = {"role": "user", "content": request.message}
            all_messages = list(existing_messages) + [new_message]

            input_state = {
                "messages": all_messages,
                "metadata": request.metadata,
            }

            result = await server_state.graph.ainvoke(
                input_state,
                run_config,
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
            if conversation_store is not None:
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
        The agent sees the full conversation history.
        """
        check_rate_limit(request.user_id)

        if server_state.graph is None:
            raise HTTPException(status_code=503, detail="Agent graph not loaded")

        run_config = {"configurable": {"thread_id": request.thread_id}}

        # ── Load existing thread state for conversation history ──────────
        existing_messages: list[dict | Any] = []
        try:
            state = await server_state.graph.aget_state(run_config)
            if state is not None and hasattr(state, "values"):
                stored = state.values.get("messages", [])
                if stored:
                    existing_messages = list(stored)
        except Exception:
            pass  # First call for this thread — no state yet

        new_message: dict | Any = {"role": "user", "content": request.message}
        all_messages = list(existing_messages) + [new_message]

        input_state = {
            "messages": all_messages,
            "metadata": request.metadata,
        }

        async def event_stream():
            try:
                async for event in server_state.graph.astream_events(
                    input_state,
                    run_config,
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
        if conversation_store is None:
            return []
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
        if conversation_store is None:
            raise HTTPException(status_code=503, detail="Conversation store not ready")
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
        if conversation_store is None:
            raise HTTPException(status_code=503, detail="Conversation store not ready")
        if conversation_store.delete(thread_id):
            return {"status": "deleted", "thread_id": thread_id}
        # Still return success — record may have already been cleaned up
        return {"status": "not_found", "thread_id": thread_id}

    @app.patch("/conversations/{thread_id}")
    async def update_conversation(thread_id: str, request: Request):
        """Update conversation metadata (e.g. rename title)."""
        if conversation_store is None:
            raise HTTPException(status_code=503, detail="Conversation store not ready")
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