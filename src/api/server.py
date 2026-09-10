"""FastAPI server for agent communication — invoke, stream, state, health.

Endpoints:
- ``POST /invoke`` — synchronous agent invocation
- ``POST /stream`` — streaming agent response (SSE)
- ``GET /state/{thread_id}`` — get thread checkpoint state
- ``POST /state/{thread_id}`` — update thread state (interrupt resume)
- ``GET /health`` — health check
- ``GET /metrics`` — runtime metrics
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from src.config import config
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.api.rate_limit import RateLimiter
from src.memory.memory_backend import UserContext

logger = logging.getLogger(__name__)


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


# ── Lifespan ──────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize resources on startup."""
    logger.info("Initializing agent server...")
    server_state.started_at = time.time()

    # Import the compiled graph (lazy, so server.py doesn't need LLM keys at import)
    try:
        from src.agent.server import graph
        server_state.graph = graph
        logger.info("Agent graph loaded successfully")
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
            messages_out = []
            for m in messages[-5:]:
                if hasattr(m, "content"):
                    messages_out.append({"role": getattr(m, "role", ""), "content": m.content})
                else:
                    messages_out.append({"role": m.get("role", ""), "content": m.get("content", "")})
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