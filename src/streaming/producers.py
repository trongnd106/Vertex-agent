"""Streaming types, chunk schema, and producers for real-time agent output.

Provides:
- ``StreamChunk`` — universal chunk dataclass for streaming deltas
- ``ToolCallDelta`` — tool call fragment during streaming
- ``StreamProducer`` — base class for all producers
- ``LangGraphProducer`` — wraps ``CompiledStateGraph.astream()``
- ``OpenAIProducer`` — wraps OpenAI streaming API
- ``SimulatedProducer`` — fake data for testing
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from src.tools.filesystem import ToolResult


# ── Chunk schema ──────────────────────────────────────────────────────


@dataclass
class ToolCallDelta:
    """A fragment of a tool call received during streaming.

    Attributes:
        id: Tool call ID (may be partial for early fragments).
        name: Tool name or empty for early fragments.
        args: Partial JSON arguments string.
        raw: Raw delta from the provider.
    """

    id: str = ""
    name: str = ""
    args: str = ""
    raw: str = ""


@dataclass
class StreamChunk:
    """A single chunk of streaming agent output.

    Attributes:
        content: Text content delta.
        reasoning: Reasoning/thinking delta.
        tool_calls: Tool call fragments in this chunk.
        tool_result: Completed tool execution result.
        finish_reason: ``"stop"`` | ``"length"`` | ``"tool_calls"`` | ``"cancelled"``.
        id: Unique chunk identifier.
        model: Model name that produced this chunk.
        node_name: Graph node that produced this chunk.
        extra: Extra metadata.
        raw: Raw provider response fragment.
        meta: Arbitrary metadata key-value pairs.
        created_at: Unix timestamp of chunk creation.
    """

    content: str | None = None
    reasoning: str | None = None
    tool_calls: list[ToolCallDelta] = field(default_factory=list)
    tool_result: ToolResult | None = None
    finish_reason: str | None = None
    id: str = ""
    model: str = ""
    node_name: str = ""
    extra: dict[str, Any] | None = None
    raw: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize chunk to a JSON-compatible dict."""
        d: dict[str, Any] = {
            "id": self.id,
            "content": self.content,
            "reasoning": self.reasoning,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "args": tc.args}
                for tc in self.tool_calls
            ],
            "tool_result": {
                "success": self.tool_result.success,
                "data": str(self.tool_result.data)[:1000] if self.tool_result else None,
                "error": self.tool_result.error if self.tool_result else None,
            } if self.tool_result else None,
            "finish_reason": self.finish_reason,
            "model": self.model,
            "node_name": self.node_name,
            "created_at": self.created_at,
        }
        if self.extra:
            d["extra"] = self.extra
        if self.meta:
            d["meta"] = self.meta
        return d

    def is_empty(self) -> bool:
        """Check if chunk contains no deltas."""
        return (
            self.content is None
            and self.reasoning is None
            and len(self.tool_calls) == 0
            and self.tool_result is None
            and self.finish_reason is None
        )


# ── Producers ─────────────────────────────────────────────────────────


class StreamProducer:
    """Base class for stream producers.

    Producers convert provider-specific streaming responses
    into a uniform ``StreamChunk`` iterator.
    """

    async def produce(self, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        """Yield ``StreamChunk`` instances from a streaming source.

        Args:
            **kwargs: Provider-specific parameters.

        Yields:
            ``StreamChunk`` instances.
        """
        if False:
            yield  # pragma: no cover — makes this an async generator

    async def __call__(self, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        async for chunk in self.produce(**kwargs):
            yield chunk


class SimulatedProducer(StreamProducer):
    """Producer that yields fake ``StreamChunk`` instances for testing.

    Simulates an LLM response with reasoning, content, and tool calls.
    """

    def __init__(
        self,
        *,
        model: str = "simulated",
        node_name: str = "agent",
        delay: float = 0.01,
    ) -> None:
        self._model = model
        self._node_name = node_name
        self._delay = delay

    async def produce(self, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        import asyncio

        # Reasoning delta
        await asyncio.sleep(self._delay)
        yield StreamChunk(
            reasoning="Thinking about the problem...",
            model=self._model,
            node_name=self._node_name,
        )

        # Content deltas
        words = ["Hello", ", ", "world", "!"]
        for word in words:
            await asyncio.sleep(self._delay)
            yield StreamChunk(
                content=word,
                model=self._model,
                node_name=self._node_name,
            )

        # Tool calls
        await asyncio.sleep(self._delay)
        yield StreamChunk(
            tool_calls=[ToolCallDelta(id="call_1", name="search", args='{"query": "test"}')],
            model=self._model,
            node_name=self._node_name,
        )

        # Finish
        yield StreamChunk(
            finish_reason="stop",
            model=self._model,
            node_name=self._node_name,
        )


class LangGraphProducer(StreamProducer):
    """Producer that wraps a LangGraph compiled graph's ``astream()``.

    Converts LangGraph stream events into ``StreamChunk`` instances.
    """

    def __init__(
        self,
        graph: Any,
        *,
        model: str = "default",
        mode: str = "messages",
    ) -> None:
        self._graph = graph
        self._model = model
        self._mode = mode

    async def produce(self, input_data: dict[str, Any], **kwargs: Any) -> AsyncIterator[StreamChunk]:
        """Produce chunks from a LangGraph graph invocation.

        Args:
            input_data: Input state dict for the graph.
            **kwargs: Extra kwargs passed to ``astream()``.

        Yields:
            ``StreamChunk`` instances from graph events.
        """
        try:
            async for event in self._graph.astream(input_data, **kwargs):
                chunk = self._convert_event(event)
                if chunk is not None:
                    yield chunk
        except Exception as e:
            yield StreamChunk(
                finish_reason="error",
                meta={"error": str(e)},
                model=self._model,
            )

    def _convert_event(self, event: Any) -> StreamChunk | None:
        """Convert a LangGraph stream event to a ``StreamChunk``."""
        from langgraph.graph import Command as LGCommand

        chunk = StreamChunk(model=self._model)

        if isinstance(event, dict):
            # messages-mode: {"agent": {"messages": [AIMessageChunk]}}
            for node_name, data in event.items():
                chunk.node_name = node_name
                messages = data.get("messages", []) if isinstance(data, dict) else []
                for msg in messages:
                    self._from_message(msg, chunk)
        elif hasattr(event, "content"):
            self._from_message(event, chunk)
        else:
            chunk.extra = {"raw_event": str(event)[:500]}

        return chunk if not chunk.is_empty() else None

    def _from_message(self, msg: Any, chunk: StreamChunk) -> None:
        """Extract chunk fields from an AI message."""
        try:
            if hasattr(msg, "content") and msg.content:
                chunk.content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)

            if hasattr(msg, "additional_kwargs"):
                kwargs = msg.additional_kwargs or {}
                if "reasoning" in kwargs:
                    chunk.reasoning = kwargs["reasoning"]

            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in (msg.tool_calls or []):
                    chunk.tool_calls.append(ToolCallDelta(
                        id=tc.get("id", ""),
                        name=tc.get("name", ""),
                        args=json.dumps(tc.get("args", {})),
                    ))

            if hasattr(msg, "response_metadata") and msg.response_metadata:
                meta = msg.response_metadata or {}
                if "finish_reason" in meta:
                    chunk.finish_reason = meta["finish_reason"]
        except Exception:
            pass


class OpenAIProducer(StreamProducer):
    """Producer that wraps OpenAI's streaming chat completions API.

    Converts ``OpenAI.chat.completions.create(stream=True)`` responses
    into ``StreamChunk`` instances.
    """

    def __init__(
        self,
        client: Any,
        model: str = "gpt-4o",
        **default_params: Any,
    ) -> None:
        self._client = client
        self._model = model
        self._default_params = default_params

    async def produce(self, messages: list[dict[str, Any]], **kwargs: Any) -> AsyncIterator[StreamChunk]:
        """Produce chunks from an OpenAI streaming response.

        Args:
            messages: Chat messages for the API.
            **kwargs: Override default params.

        Yields:
            ``StreamChunk`` instances.
        """
        params = {**self._default_params, **kwargs, "stream": True}
        params.setdefault("model", self._model)

        try:
            response = await self._client.chat.completions.create(
                messages=messages,
                **params,
            )

            async for part in response:
                chunk = StreamChunk(model=self._model)
                delta = part.choices[0].delta if part.choices else None
                if delta is None:
                    continue

                if delta.content:
                    chunk.content = delta.content
                if hasattr(delta, "reasoning") and delta.reasoning:
                    chunk.reasoning = delta.reasoning

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        chunk.tool_calls.append(ToolCallDelta(
                            id=tc.id or "",
                            name=tc.function.name if tc.function else "",
                            args=tc.function.arguments if tc.function else "",
                        ))

                finish = part.choices[0].finish_reason if part.choices else None
                if finish:
                    chunk.finish_reason = finish

                if not chunk.is_empty():
                    yield chunk

        except Exception as e:
            yield StreamChunk(
                finish_reason="error",
                meta={"error": str(e)},
                model=self._model,
            )


__all__ = [
    "LangGraphProducer",
    "OpenAIProducer",
    "SimulatedProducer",
    "StreamChunk",
    "StreamProducer",
    "ToolCallDelta",
]