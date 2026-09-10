"""Gateway integration — real-time UI communication via HTTP and WebSocket.

Provides:
- ``GatewayConfig`` — configuration for gateway connections
- ``HTTPGateway`` — POST chunks to an HTTP endpoint
- ``WebSocketGateway`` — real-time WebSocket push
- ``GatewayManager`` — manages multiple gateway connections
- ``BackpressureController`` — flow control when gateway is slow
- ``BatchBuffer`` — batch chunks for efficient sending
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.streaming.producers import StreamChunk
from src.streaming.transport import StreamConsumer, StreamTransport, Tee


# ── Event types ───────────────────────────────────────────────────────


class GatewayEventType(str, Enum):
    REASONING = "reasoning"
    CONTENT = "content"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    FINISH = "finish"


def classify_chunk(chunk: StreamChunk) -> GatewayEventType:
    """Classify a chunk into a gateway event type."""
    if chunk.finish_reason:
        return GatewayEventType.FINISH
    if chunk.meta and "error" in chunk.meta:
        return GatewayEventType.ERROR
    if chunk.tool_result:
        return GatewayEventType.TOOL_RESULT
    if chunk.tool_calls:
        return GatewayEventType.TOOL_CALL
    if chunk.reasoning:
        return GatewayEventType.REASONING
    return GatewayEventType.CONTENT


# ── Configuration ─────────────────────────────────────────────────────


@dataclass
class GatewayConfig:
    """Configuration for a gateway connection.

    Attributes:
        url: Gateway endpoint URL.
        api_key: API key for authentication.
        headers: Additional HTTP headers.
        timeout: Request timeout in seconds.
        max_retries: Maximum reconnection attempts.
        retry_delay: Delay between reconnection attempts.
        batch_size: Number of chunks to batch (0 = no batching).
        batch_interval_ms: Max wait time for batching in ms.
        max_queue_size: Max queued chunks before backpressure.
    """

    url: str = ""
    api_key: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    batch_size: int = 0
    batch_interval_ms: int = 100
    max_queue_size: int = 1000


# ── Backpressure ──────────────────────────────────────────────────────


class BackpressureController:
    """Flow control when the gateway is slow.

    Monitors queue depth and applies backpressure strategies:
    - ``"block"`` — block producer until queue drains
    - ``"drop"`` — drop chunks when queue is full
    - ``"throttle"`` — slow down producer by ``throttle_delay``
    """

    def __init__(
        self,
        strategy: str = "block",
        max_queue_size: int = 1000,
        throttle_delay: float = 0.01,
    ) -> None:
        self._strategy = strategy
        self._max_queue_size = max_queue_size
        self._throttle_delay = throttle_delay
        self._current_size = 0
        self._dropped = 0

    @property
    def dropped_count(self) -> int:
        return self._dropped

    def check(self, queue_size: int) -> bool:
        """Check if a chunk can be accepted.

        Args:
            queue_size: Current queue size.

        Returns:
            True if the chunk should be accepted.
        """
        self._current_size = queue_size
        if queue_size >= self._max_queue_size:
            if self._strategy == "drop":
                self._dropped += 1
                return False
            elif self._strategy == "throttle":
                time.sleep(self._throttle_delay)
                return True
            else:  # block
                time.sleep(0.01)
                return self.check(queue_size)
        return True


# ── Batch buffer ──────────────────────────────────────────────────────


class BatchBuffer:
    """Buffer chunks and flush them as batches."""

    def __init__(
        self,
        max_size: int = 10,
        max_interval_ms: int = 100,
    ) -> None:
        self._max_size = max_size
        self._max_interval_ms = max_interval_ms
        self._buffer: list[StreamChunk] = []
        self._last_flush = time.time()

    def add(self, chunk: StreamChunk) -> list[StreamChunk] | None:
        """Add a chunk to the buffer.

        Returns:
            A list of chunks to flush if the buffer is ready,
            or None if still buffering.
        """
        self._buffer.append(chunk)
        if len(self._buffer) >= self._max_size:
            return self.flush()
        elapsed_ms = (time.time() - self._last_flush) * 1000
        if elapsed_ms >= self._max_interval_ms:
            return self.flush()
        return None

    def flush(self) -> list[StreamChunk] | None:
        """Flush the buffer.

        Returns:
            The buffered chunks, or None if empty.
        """
        if not self._buffer:
            return None
        chunks = self._buffer
        self._buffer = []
        self._last_flush = time.time()
        return chunks


# ── HTTP gateway ──────────────────────────────────────────────────────


class HTTPGateway:
    """Gateway that sends chunks to an HTTP endpoint.

    Uses POST requests with NDJSON body for batch or single-chunk
    delivery.
    """

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._session: Any = None
        self._closed = False

    async def connect(self) -> None:
        """Open a persistent HTTP session."""
        import httpx
        headers = {
            "Content-Type": "application/x-ndjson",
            **self._config.headers,
        }
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        self._session = httpx.AsyncClient(
            headers=headers,
            timeout=self._config.timeout,
        )

    async def send_chunk(self, chunk: StreamChunk) -> bool:
        """Send a single chunk to the gateway.

        Returns:
            True if successful.
        """
        if self._closed or self._session is None:
            return False
        try:
            event_type = classify_chunk(chunk).value
            data = chunk.to_dict()
            data["event"] = event_type
            response = await self._session.post(
                self._config.url,
                content=json.dumps(data, ensure_ascii=False) + "\n",
            )
            return response.is_success
        except Exception:
            return False

    async def send_batch(self, chunks: list[StreamChunk]) -> bool:
        """Send a batch of chunks as NDJSON.

        Returns:
            True if successful.
        """
        if self._closed or self._session is None or not chunks:
            return False
        try:
            lines = []
            for chunk in chunks:
                data = chunk.to_dict()
                data["event"] = classify_chunk(chunk).value
                lines.append(json.dumps(data, ensure_ascii=False))
            response = await self._session.post(
                self._config.url,
                content="\n".join(lines) + "\n",
            )
            return response.is_success
        except Exception:
            return False

    async def close(self) -> None:
        if self._session:
            await self._session.aclose()
        self._closed = True


# ── WebSocket gateway ─────────────────────────────────────────────────


class WebSocketGateway:
    """Gateway that pushes chunks over a WebSocket connection.

    Automatically reconnects on disconnection.
    """

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._ws: Any = None
        self._closed = False

    async def connect(self) -> None:
        """Open a WebSocket connection."""
        import websockets
        headers = dict(self._config.headers)
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        self._ws = await websockets.connect(
            self._config.url,
            extra_headers=headers,
            ping_interval=20,
            ping_timeout=10,
        )

    async def send_chunk(self, chunk: StreamChunk) -> bool:
        """Send a chunk as a JSON WebSocket message.

        Returns:
            True if successful.
        """
        if self._closed or self._ws is None:
            return False
        try:
            data = chunk.to_dict()
            data["event"] = classify_chunk(chunk).value
            await self._ws.send(json.dumps(data, ensure_ascii=False))
            return True
        except Exception:
            await self._reconnect()
            return False

    async def send_batch(self, chunks: list[StreamChunk]) -> bool:
        """Send multiple chunks as a single JSON array.

        Returns:
            True if successful.
        """
        if self._closed or self._ws is None or not chunks:
            return False
        try:
            batch = []
            for chunk in chunks:
                data = chunk.to_dict()
                data["event"] = classify_chunk(chunk).value
                batch.append(data)
            await self._ws.send(json.dumps({"batch": batch}, ensure_ascii=False))
            return True
        except Exception:
            return False

    async def _reconnect(self) -> None:
        """Attempt to reconnect."""
        for attempt in range(self._config.max_retries):
            try:
                await asyncio.sleep(self._config.retry_delay * (attempt + 1))
                await self.connect()
                return
            except Exception:
                continue

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
        self._closed = True


# ── Gateway manager ───────────────────────────────────────────────────


class GatewayManager:
    """Manages multiple gateway connections and integrates with transport.

    Connects to the transport pipeline via the ``StreamConsumer`` interface.
    """

    def __init__(self, config: GatewayConfig | None = None) -> None:
        self._config = config or GatewayConfig()
        self._http_gateway: HTTPGateway | None = None
        self._ws_gateway: WebSocketGateway | None = None
        self._backpressure = BackpressureController(
            max_queue_size=self._config.max_queue_size,
        )
        self._batch_buffer = BatchBuffer(
            max_size=self._config.batch_size or 0,
            max_interval_ms=self._config.batch_interval_ms,
        )
        self._use_batching = self._config.batch_size > 0
        self._sent_count = 0

    def connect_http(self, url: str, api_key: str = "") -> HTTPGateway:
        """Add an HTTP gateway.

        Returns:
            The created ``HTTPGateway``.
        """
        self._config.url = url
        if api_key:
            self._config.api_key = api_key
        self._http_gateway = HTTPGateway(self._config)
        return self._http_gateway

    def connect_ws(self, url: str, api_key: str = "") -> WebSocketGateway:
        """Add a WebSocket gateway.

        Returns:
            The created ``WebSocketGateway``.
        """
        gw = WebSocketGateway(
            GatewayConfig(
                url=url,
                api_key=api_key,
                max_retries=self._config.max_retries,
                retry_delay=self._config.retry_delay,
            )
        )
        self._ws_gateway = gw
        return gw

    async def start(self) -> None:
        """Open all gateway connections."""
        if self._http_gateway:
            await self._http_gateway.connect()
        if self._ws_gateway:
            await self._ws_gateway.connect()

    async def send_chunk(self, chunk: StreamChunk) -> bool:
        """Send a chunk to all connected gateways.

        Returns:
            True if at least one gateway accepted the chunk.
        """
        if not self._backpressure.check(0):
            return False

        success = False

        if self._use_batching:
            batch = self._batch_buffer.add(chunk)
            if batch:
                if self._http_gateway:
                    if await self._http_gateway.send_batch(batch):
                        success = True
                if self._ws_gateway:
                    if await self._ws_gateway.send_batch(batch):
                        success = True
                self._sent_count += len(batch)
        else:
            if self._http_gateway:
                if await self._http_gateway.send_chunk(chunk):
                    success = True
            if self._ws_gateway:
                if await self._ws_gateway.send_chunk(chunk):
                    success = True
            self._sent_count += 1

        return success

    async def flush(self) -> None:
        """Flush any buffered chunks."""
        if not self._use_batching:
            return
        batch = self._batch_buffer.flush()
        if batch:
            if self._http_gateway:
                await self._http_gateway.send_batch(batch)
            if self._ws_gateway:
                await self._ws_gateway.send_batch(batch)

    async def close(self) -> None:
        """Close all gateway connections."""
        if self._http_gateway:
            await self._http_gateway.close()
        if self._ws_gateway:
            await self._ws_gateway.close()

    @property
    def sent_count(self) -> int:
        return self._sent_count

    def create_consumer(self) -> StreamConsumer:
        """Create a ``StreamConsumer`` for use with ``Tee``/``StreamTransport``."""
        async def consumer(chunk: StreamChunk) -> None:
            await self.send_chunk(chunk)
        return consumer


__all__ = [
    "BackpressureController",
    "BatchBuffer",
    "GatewayConfig",
    "GatewayEventType",
    "GatewayManager",
    "HTTPGateway",
    "WebSocketGateway",
    "classify_chunk",
]