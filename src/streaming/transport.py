"""Stream transport layer — forward chunks with retry, tee, cancellation.

Provides:
- ``StreamTransport`` — core transport that forwards ``StreamChunk`` via consumers
- ``Tee`` — fan-out to multiple consumers simultaneously
- ``RetryPolicy`` — exponential backoff for mid-stream failures
- ``CancelToken`` — cooperative cancellation for streaming
- ``StreamCollector`` — collect chunks into a list for debugging/analysis
- ``FileDebugPrinter`` — write debug trace to file
"""

from __future__ import annotations

import time
import uuid
import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from src.streaming.producers import StreamChunk


# ── Retry policy ──────────────────────────────────────────────────────


@dataclass
class RetryPolicy:
    """Configuration for mid-stream retry behaviour.

    Attributes:
        max_attempts: Maximum number of retry attempts.
        initial_backoff: Initial backoff in seconds.
        max_backoff: Maximum backoff in seconds.
        backoff_factor: Multiplicative factor for exponential backoff.
        retry_statuses: HTTP status codes that trigger a retry.
        max_replay_bytes: Maximum bytes to buffer for replay on failure.
    """

    max_attempts: int = 3
    initial_backoff: float = 1.0
    max_backoff: float = 60.0
    backoff_factor: float = 2.0
    retry_statuses: set[int] = field(default_factory=lambda: {429, 502, 503, 504})
    max_replay_bytes: int = 2 * 1024 * 1024  # 2 MB

    def get_backoff(self, attempt: int) -> float:
        """Calculate backoff for a given attempt number."""
        backoff = self.initial_backoff * (self.backoff_factor ** (attempt - 1))
        return min(backoff, self.max_backoff)


# ── Cancellation ──────────────────────────────────────────────────────


class CancelToken:
    """Cooperative cancellation token for streaming operations.

    Usage:
        token = CancelToken()
        # pass to transport
        token.cancel()  # signal cancellation from another task
    """

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        """Signal cancellation."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been signalled."""
        return self._cancelled

    def check(self) -> None:
        """Raise ``CancelledError`` if cancelled."""
        if self._cancelled:
            raise CancelledError("Stream cancelled")


class CancelledError(Exception):
    """Raised when a streaming operation is cancelled."""
    pass


# ── Stream collector ──────────────────────────────────────────────────


class StreamCollector:
    """Collects chunks into a list for debugging or analysis."""

    def __init__(self) -> None:
        self._chunks: list[StreamChunk] = []

    async def __call__(self, chunk: StreamChunk) -> None:
        self._chunks.append(chunk)

    @property
    def chunks(self) -> list[StreamChunk]:
        return list(self._chunks)

    def clear(self) -> None:
        self._chunks.clear()

    def to_dicts(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self._chunks]


# ── File debug printer ────────────────────────────────────────────────


class FileDebugPrinter:
    """Write streaming debug trace to a file."""

    def __init__(self, path: str) -> None:
        self._path = path

    async def __call__(self, chunk: StreamChunk) -> None:
        with open(self._path, "a") as f:
            fields = []
            if chunk.content:
                fields.append(f"content={repr(chunk.content[:80])}")
            if chunk.reasoning:
                fields.append(f"reasoning={repr(chunk.reasoning[:80])}")
            if chunk.tool_calls:
                fields.append(f"tool_calls={[tc.name for tc in chunk.tool_calls]}")
            if chunk.finish_reason:
                fields.append(f"finish={chunk.finish_reason}")
            line = f"[{chunk.node_name}] {', '.join(fields)}\n"
            f.write(line)


# ── Tee ───────────────────────────────────────────────────────────────


StreamConsumer = Callable[[StreamChunk], Any]
"""Type alias for a chunk consumer."""


class Tee:
    """Fan-out stream chunks to multiple consumers.

    Each consumer receives every chunk in the order it was produced.
    """

    def __init__(self, *consumers: StreamConsumer) -> None:
        self._consumers = list(consumers)

    def add(self, consumer: StreamConsumer) -> None:
        """Add a consumer."""
        self._consumers.append(consumer)

    def remove(self, consumer: StreamConsumer) -> None:
        """Remove a consumer."""
        self._consumers.remove(consumer)

    async def emit(self, chunk: StreamChunk) -> None:
        """Emit a chunk to all consumers."""
        for consumer in self._consumers:
            try:
                result = consumer(chunk)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception:
                pass

    def __len__(self) -> int:
        return len(self._consumers)


# ── Stream transport ──────────────────────────────────────────────────


class StreamTransport:
    """Core transport that forwards ``StreamChunk`` instances through a pipeline.

    The transport reads chunks from a producer (async iterator) and
    forwards them through a ``Tee`` to multiple consumers, with
    optional retry and cancellation support.

    Usage:
        transport = StreamTransport()
        transport.connect(producer, tee)
        await transport.run(input_data={"messages": [...]})
    """

    def __init__(
        self,
        retry_policy: RetryPolicy | None = None,
        cancel_token: CancelToken | None = None,
    ) -> None:
        self._producer: Any = None
        self._tee: Tee | None = None
        self._retry_policy = retry_policy or RetryPolicy()
        self._cancel_token = cancel_token or CancelToken()
        self._chunk_count = 0
        self._last_chunk: StreamChunk | None = None

    def connect(self, producer: Any, tee: Tee) -> None:
        """Connect producer and tee to the transport.

        Args:
            producer: A ``StreamProducer`` instance.
            tee: A ``Tee`` to fan-out chunks.
        """
        self._producer = producer
        self._tee = tee

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    @property
    def last_chunk(self) -> StreamChunk | None:
        return self._last_chunk

    async def run(self, **kwargs: Any) -> None:
        """Run the transport, forwarding chunks from producer to consumers.

        Args:
            **kwargs: Arguments passed to the producer.

        Raises:
            CancelledError: If cancelled via ``CancelToken``.
        """
        if self._producer is None or self._tee is None:
            raise RuntimeError("Transport not connected. Call connect() first.")

        self._chunk_count = 0

        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                async for chunk in self._producer(**kwargs):
                    self._cancel_token.check()
                    self._last_chunk = chunk
                    await self._tee.emit(chunk)
                    self._chunk_count += 1
                break  # completed successfully
            except CancelledError:
                raise
            except Exception as e:
                if attempt >= self._retry_policy.max_attempts:
                    error_chunk = StreamChunk(
                        finish_reason="error",
                        meta={"error": str(e), "attempts": attempt},
                    )
                    await self._tee.emit(error_chunk)
                    raise
                backoff = self._retry_policy.get_backoff(attempt)
                time.sleep(backoff)

    async def run_and_collect(self, **kwargs: Any) -> list[StreamChunk]:
        """Run transport and collect all chunks.

        Args:
            **kwargs: Arguments passed to the producer.

        Returns:
            List of all ``StreamChunk`` instances produced.
        """
        collector = StreamCollector()
        if self._tee is None:
            self._tee = Tee(collector)
        else:
            self._tee.add(collector)

        try:
            await self.run(**kwargs)
        finally:
            if self._tee is not None:
                self._tee.remove(collector)

        return collector.chunks


__all__ = [
    "CancelToken",
    "CancelledError",
    "FileDebugPrinter",
    "RetryPolicy",
    "StreamCollector",
    "StreamConsumer",
    "StreamTransport",
    "Tee",
]