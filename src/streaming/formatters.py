"""Stream formatters — convert ``StreamChunk`` instances to output formats.

Provides:
- ``StreamFormatter`` — base class
- ``ChatboxFormatter`` — NDJSON format for production
- ``OpenAIFormatter`` — SSE or NDJSON (OpenAI Chat Completions format)
- ``ClaudeFormatter`` — SSE block-based (text_delta, thinking_delta, tool_use, tool_result)
- ``FormatterFactory`` — create formatter based on config
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from src.streaming.producers import StreamChunk


# ── Base class ────────────────────────────────────────────────────────


class StreamFormatter(ABC):
    """Base class for stream formatters.

    Formatters convert ``StreamChunk`` instances into formatted string
    representations suitable for different output protocols.
    """

    @abstractmethod
    def format(self, chunk: StreamChunk) -> str:
        """Format a single chunk into a string."""
        ...

    def format_event(self, event_type: str, chunk: StreamChunk) -> str:
        """Format a chunk with an event type prefix."""
        return self.format(chunk)

    async def format_stream(
        self, chunks: AsyncIterator[StreamChunk],
    ) -> AsyncIterator[str]:
        """Format an async stream of chunks."""
        async for chunk in chunks:
            yield self.format(chunk)


# ── Chatbox formatter (NDJSON) ────────────────────────────────────────


class ChatboxFormatter(StreamFormatter):
    """NDJSON formatter for production chatbox consumption.

    Each chunk is serialized as a single JSON line (NDJSON).
    """

    def format(self, chunk: StreamChunk) -> str:
        """Format a chunk as a JSON line."""
        return json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n"

    def format_event(self, event_type: str, chunk: StreamChunk) -> str:
        """Format a chunk as a JSON line with event type."""
        data = chunk.to_dict()
        data["event"] = event_type
        return json.dumps(data, ensure_ascii=False) + "\n"


# ── OpenAI formatter (SSE) ────────────────────────────────────────────


class OpenAIFormatter(StreamFormatter):
    """SSE formatter matching OpenAI Chat Completions streaming format.

    Produces ``data: {...}\n\n`` lines compatible with the OpenAI
    streaming API spec.
    """

    def __init__(self, model: str = "default") -> None:
        self._model = model

    def format(self, chunk: StreamChunk) -> str:
        """Format a chunk as an SSE ``data:`` line."""
        delta: dict[str, Any] = {"role": "assistant", "content": ""}
        if chunk.content:
            delta["content"] = chunk.content
        if chunk.reasoning:
            delta["reasoning"] = chunk.reasoning
        if chunk.tool_calls:
            delta["tool_calls"] = [
                {
                    "index": i,
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.args},
                }
                for i, tc in enumerate(chunk.tool_calls)
            ]

        choice: dict[str, Any] = {
            "index": 0,
            "delta": delta,
        }
        if chunk.finish_reason:
            choice["finish_reason"] = chunk.finish_reason

        data = {
            "id": chunk.id,
            "object": "chat.completion.chunk",
            "created": int(chunk.created_at),
            "model": chunk.model or self._model,
            "choices": [choice],
        }
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def format_event(self, event_type: str, chunk: StreamChunk) -> str:
        """Format as SSE with event type line."""
        base = self.format(chunk)
        return f"event: {event_type}\n{base}"


# ── Claude formatter (SSE block-based) ────────────────────────────────


class ClaudeFormatter(StreamFormatter):
    """SSE block-based formatter matching Claude's streaming format.

    Produces ``event: text_delta\n data: {...}\n\n`` lines compatible
    with Anthropic's Messages API streaming.
    """

    def __init__(self, model: str = "default") -> None:
        self._model = model
        self._message_id: str = ""

    def format(self, chunk: StreamChunk) -> str:
        """Auto-detect the Claude event type and format."""
        if chunk.finish_reason:
            return self._format_stop(chunk)
        if chunk.content:
            return self._format_text_delta(chunk)
        if chunk.reasoning:
            return self._format_thinking_delta(chunk)
        if chunk.tool_calls:
            return self._format_tool_use(chunk)
        if chunk.tool_result:
            return self._format_tool_result(chunk)
        return ""

    def _format_text_delta(self, chunk: StreamChunk) -> str:
        data = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {
                "type": "text_delta",
                "text": chunk.content or "",
            },
        }
        return f"event: content_block_delta\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _format_thinking_delta(self, chunk: StreamChunk) -> str:
        data = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {
                "type": "thinking_delta",
                "thinking": chunk.reasoning or "",
            },
        }
        return f"event: content_block_delta\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _format_tool_use(self, chunk: StreamChunk) -> str:
        if not chunk.tool_calls:
            return ""
        tc = chunk.tool_calls[0]
        data = {
            "type": "content_block_delta",
            "index": 1,
            "delta": {
                "type": "tool_call_delta",
                "id": tc.id,
                "name": tc.name,
                "input": tc.args,
            },
        }
        return f"event: content_block_delta\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _format_tool_result(self, chunk: StreamChunk) -> str:
        tr = chunk.tool_result
        data = {
            "type": "tool_result",
            "index": 1,
            "content": str(tr.data if tr and tr.data else ""),
            "success": tr.success if tr else True,
        }
        return f"event: tool_result\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _format_stop(self, chunk: StreamChunk) -> str:
        data = {
            "type": "message_stop",
            "finish_reason": chunk.finish_reason,
        }
        return f"event: message_stop\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Formatter factory ─────────────────────────────────────────────────


class FormatterFactory:
    """Factory that creates a ``StreamFormatter`` based on config."""

    FORMATTERS: dict[str, type[StreamFormatter]] = {
        "chatbox": ChatboxFormatter,
        "openai": OpenAIFormatter,
        "claude": ClaudeFormatter,
    }

    @classmethod
    def create(
        cls,
        format_type: str,
        **kwargs: Any,
    ) -> StreamFormatter:
        """Create a formatter by type name.

        Args:
            format_type: One of ``"chatbox"``, ``"openai"``, ``"claude"``.
            **kwargs: Passed to the formatter constructor.

        Returns:
            A ``StreamFormatter`` instance.

        Raises:
            ValueError: If ``format_type`` is unknown.
        """
        formatter_cls = cls.FORMATTERS.get(format_type)
        if formatter_cls is None:
            raise ValueError(
                f"Unknown formatter: '{format_type}'. "
                f"Available: {list(cls.FORMATTERS.keys())}"
            )
        return formatter_cls(**kwargs)

    @classmethod
    def register(cls, name: str, formatter_cls: type[StreamFormatter]) -> None:
        """Register a custom formatter."""
        cls.FORMATTERS[name] = formatter_cls


__all__ = [
    "ChatboxFormatter",
    "ClaudeFormatter",
    "FormatterFactory",
    "OpenAIFormatter",
    "StreamFormatter",
]