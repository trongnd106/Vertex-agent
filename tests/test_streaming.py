"""Tests for the streaming & observability package.

Covers:
- Task 6.1: StreamChunk Schema & Producers
- Task 6.2: Stream Transport Layer
- Task 6.3: Stream Formatters
- Task 6.4: Observability & Tracing
- Task 6.5: Gateway Integration
"""

from __future__ import annotations

import json
import os
import time

import pytest

from src.streaming import (
    # producers
    LangGraphProducer,
    OpenAIProducer,
    SimulatedProducer,
    StreamChunk,
    StreamProducer,
    ToolCallDelta,
    # transport
    CancelToken,
    CancelledError,
    FileDebugPrinter,
    RetryPolicy,
    StreamCollector,
    StreamTransport,
    Tee,
    # formatters
    ChatboxFormatter,
    ClaudeFormatter,
    FormatterFactory,
    OpenAIFormatter,
    StreamFormatter,
    # observability
    DebugMode,
    DebugSnapshot,
    HealthCheck,
    HealthStatus,
    MetricsCollector,
    MetricSnapshot,
    Span,
    StructuredLogger,
    Tracer,
    # gateway
    BackpressureController,
    BatchBuffer,
    GatewayConfig,
    GatewayEventType,
    GatewayManager,
    HTTPGateway,
    WebSocketGateway,
    classify_chunk,
)


# ═══════════════════════════════════════════════════════════════════════
# Task 6.1: StreamChunk Schema & Producers
# ═══════════════════════════════════════════════════════════════════════


class TestStreamChunk:
    def test_create_minimal(self):
        chunk = StreamChunk()
        assert chunk.id
        assert chunk.created_at > 0
        assert chunk.content is None
        assert chunk.tool_calls == []

    def test_create_with_fields(self):
        chunk = StreamChunk(
            content="Hello",
            reasoning="thinking...",
            finish_reason="stop",
            model="gpt-4",
            node_name="agent",
        )
        assert chunk.content == "Hello"
        assert chunk.reasoning == "thinking..."
        assert chunk.finish_reason == "stop"
        assert chunk.model == "gpt-4"

    def test_to_dict(self):
        chunk = StreamChunk(content="Hi", model="test")
        d = chunk.to_dict()
        assert d["content"] == "Hi"
        assert d["model"] == "test"
        assert "id" in d

    def test_to_dict_with_tool_result(self):
        from src.tools.filesystem import ToolResult
        chunk = StreamChunk(tool_result=ToolResult(success=True, data="done"))
        d = chunk.to_dict()
        assert d["tool_result"]["success"] is True

    def test_is_empty(self):
        assert StreamChunk().is_empty() is True
        assert StreamChunk(content="a").is_empty() is False
        assert StreamChunk(finish_reason="stop").is_empty() is False

    def test_idempotent_id(self):
        chunk = StreamChunk(id="fixed-id")
        assert chunk.id == "fixed-id"


class TestToolCallDelta:
    def test_create(self):
        delta = ToolCallDelta(id="call_1", name="search", args='{"q": "test"}')
        assert delta.id == "call_1"
        assert delta.name == "search"
        assert delta.args == '{"q": "test"}'

    def test_defaults(self):
        delta = ToolCallDelta()
        assert delta.id == ""
        assert delta.name == ""
        assert delta.args == ""


class TestStreamProducer:
    def test_base_class(self):
        producer = StreamProducer()
        assert isinstance(producer, StreamProducer)

    def test_produce_is_async_gen(self):
        producer = StreamProducer()
        import inspect
        assert inspect.isasyncgenfunction(producer.produce)


class TestSimulatedProducer:
    @pytest.mark.asyncio
    async def test_produces_chunks(self):
        producer = SimulatedProducer(delay=0.001)
        chunks = [c async for c in producer()]
        assert len(chunks) >= 1
        assert chunks[-1].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_includes_reasoning(self):
        producer = SimulatedProducer(delay=0.001)
        chunks = [c async for c in producer()]
        reasoning_chunks = [c for c in chunks if c.reasoning]
        assert len(reasoning_chunks) >= 1

    @pytest.mark.asyncio
    async def test_includes_content(self):
        producer = SimulatedProducer(delay=0.001)
        chunks = [c async for c in producer()]
        content = "".join(c.content or "" for c in chunks)
        assert "Hello" in content


class TestLangGraphProducer:
    def test_init(self):
        producer = LangGraphProducer(None, model="test")
        assert producer._model == "test"


# ═══════════════════════════════════════════════════════════════════════
# Task 6.2: Stream Transport Layer
# ═══════════════════════════════════════════════════════════════════════


class TestRetryPolicy:
    def test_defaults(self):
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.initial_backoff == 1.0

    def test_get_backoff(self):
        policy = RetryPolicy(initial_backoff=1.0, backoff_factor=2.0)
        assert policy.get_backoff(1) == 1.0
        assert policy.get_backoff(2) == 2.0
        assert policy.get_backoff(3) == 4.0

    def test_max_backoff(self):
        policy = RetryPolicy(initial_backoff=10.0, max_backoff=15.0, backoff_factor=3.0)
        assert policy.get_backoff(2) == 15.0  # capped


class TestCancelToken:
    def test_not_cancelled_by_default(self):
        token = CancelToken()
        assert token.is_cancelled is False

    def test_cancel(self):
        token = CancelToken()
        token.cancel()
        assert token.is_cancelled is True

    def test_check_raises(self):
        token = CancelToken()
        token.cancel()
        with pytest.raises(CancelledError):
            token.check()


class TestStreamCollector:
    def test_collect(self):
        collector = StreamCollector()
        chunks = [StreamChunk(content=str(i)) for i in range(3)]
        import asyncio
        for c in chunks:
            asyncio.run(collector(c))
        assert len(collector.chunks) == 3

    def test_clear(self):
        collector = StreamCollector()
        import asyncio
        asyncio.run(collector(StreamChunk(content="a")))
        collector.clear()
        assert len(collector.chunks) == 0

    def test_to_dicts(self):
        collector = StreamCollector()
        import asyncio
        asyncio.run(collector(StreamChunk(content="x", model="m")))
        dicts = collector.to_dicts()
        assert len(dicts) == 1
        assert dicts[0]["content"] == "x"


class TestFileDebugPrinter:
    def test_write(self, tmp_path):
        log = tmp_path / "debug.log"
        printer = FileDebugPrinter(str(log))
        import asyncio
        asyncio.run(printer(StreamChunk(content="hello", node_name="agent")))
        assert log.exists()
        content = log.read_text()
        assert "agent" in content
        assert "hello" in content


class TestTee:
    @pytest.mark.asyncio
    async def test_emit_to_multiple(self):
        results = [[], []]
        async def consumer_a(c):
            results[0].append(c)
        async def consumer_b(c):
            results[1].append(c)

        tee = Tee(consumer_a, consumer_b)
        chunk = StreamChunk(content="test")
        await tee.emit(chunk)
        assert len(results[0]) == 1
        assert len(results[1]) == 1

    def test_add_remove(self):
        tee = Tee()
        assert len(tee) == 0
        async def fake(c):
            pass
        tee.add(fake)
        assert len(tee) == 1
        tee.remove(fake)
        assert len(tee) == 0


class TestStreamTransport:
    @pytest.mark.asyncio
    async def test_run_and_collect(self):
        producer = SimulatedProducer(delay=0.001)
        transport = StreamTransport()
        tee = Tee()
        transport.connect(producer, tee)
        chunks = await transport.run_and_collect()
        assert len(chunks) >= 1
        assert transport.chunk_count > 0

    @pytest.mark.asyncio
    async def test_cancellation(self):
        async def slow_producer(**kwargs):
            for i in range(100):
                await asyncio.sleep(0.01)
                yield StreamChunk(content=str(i))

        import asyncio
        token = CancelToken()
        transport = StreamTransport(cancel_token=token)
        tee = Tee()
        transport.connect(slow_producer, tee)

        async def cancel_later():
            await asyncio.sleep(0.05)
            token.cancel()

        async def run():
            try:
                await transport.run()
            except CancelledError:
                pass

        await asyncio.gather(run(), cancel_later())
        assert token.is_cancelled

    def test_connect_required(self):
        import asyncio
        transport = StreamTransport()
        with pytest.raises(RuntimeError, match="connect"):
            asyncio.run(transport.run())


# ═══════════════════════════════════════════════════════════════════════
# Task 6.3: Stream Formatters
# ═══════════════════════════════════════════════════════════════════════


class TestChatboxFormatter:
    def test_format(self):
        formatter = ChatboxFormatter()
        chunk = StreamChunk(content="Hello", model="test")
        output = formatter.format(chunk)
        parsed = json.loads(output.strip())
        assert parsed["content"] == "Hello"

    def test_format_event(self):
        formatter = ChatboxFormatter()
        chunk = StreamChunk(content="Hi")
        output = formatter.format_event("content", chunk)
        parsed = json.loads(output.strip())
        assert parsed["event"] == "content"

    def test_format_with_tool_calls(self):
        formatter = ChatboxFormatter()
        chunk = StreamChunk(tool_calls=[ToolCallDelta(id="c1", name="search")])
        output = formatter.format(chunk)
        parsed = json.loads(output.strip())
        assert len(parsed["tool_calls"]) == 1


class TestOpenAIFormatter:
    def test_format_content(self):
        formatter = OpenAIFormatter(model="gpt-4")
        chunk = StreamChunk(content="Hello", id="chunk_1", created_at=1000)
        output = formatter.format(chunk)
        assert output.startswith("data: ")
        assert 'content": "Hello"' in output

    def test_format_finish(self):
        formatter = OpenAIFormatter()
        chunk = StreamChunk(finish_reason="stop")
        output = formatter.format(chunk)
        assert 'finish_reason": "stop"' in output

    def test_format_event(self):
        formatter = OpenAIFormatter()
        chunk = StreamChunk(content="Hi")
        output = formatter.format_event("content", chunk)
        assert output.startswith("event: content")


class TestClaudeFormatter:
    def test_text_delta(self):
        formatter = ClaudeFormatter()
        chunk = StreamChunk(content="Hello")
        output = formatter.format(chunk)
        assert "text_delta" in output
        assert "Hello" in output

    def test_thinking_delta(self):
        formatter = ClaudeFormatter()
        chunk = StreamChunk(reasoning="thinking")
        output = formatter.format(chunk)
        assert "thinking_delta" in output

    def test_tool_call(self):
        formatter = ClaudeFormatter()
        chunk = StreamChunk(tool_calls=[ToolCallDelta(id="c1", name="search")])
        output = formatter.format(chunk)
        assert "tool_call_delta" in output

    def test_finish(self):
        formatter = ClaudeFormatter()
        chunk = StreamChunk(finish_reason="stop")
        output = formatter.format(chunk)
        assert "message_stop" in output

    def test_empty_chunk(self):
        formatter = ClaudeFormatter()
        chunk = StreamChunk()
        output = formatter.format(chunk)
        assert output == ""


class TestFormatterFactory:
    def test_create_chatbox(self):
        f = FormatterFactory.create("chatbox")
        assert isinstance(f, ChatboxFormatter)

    def test_create_openai(self):
        f = FormatterFactory.create("openai", model="gpt-4")
        assert isinstance(f, OpenAIFormatter)

    def test_create_claude(self):
        f = FormatterFactory.create("claude")
        assert isinstance(f, ClaudeFormatter)

    def test_unknown(self):
        with pytest.raises(ValueError, match="Unknown"):
            FormatterFactory.create("unknown")

    def test_register_custom(self):
        class Custom(StreamFormatter):
            def format(self, chunk):
                return "custom"

        FormatterFactory.register("custom", Custom)
        f = FormatterFactory.create("custom")
        assert isinstance(f, Custom)


# ═══════════════════════════════════════════════════════════════════════
# Task 6.4: Observability & Tracing
# ═══════════════════════════════════════════════════════════════════════


class TestMetricsCollector:
    def test_record_tokens(self):
        m = MetricsCollector()
        m.record_tokens(prompt=100, completion=50)
        snap = m.snapshot()
        assert snap.token_usage["prompt"] == 100
        assert snap.token_usage["completion"] == 50
        assert snap.token_usage["total"] == 150

    def test_record_tool_execution(self):
        m = MetricsCollector()
        m.record_tool_execution("search", 150.0)
        m.record_tool_execution("search", 50.0)
        snap = m.snapshot()
        assert "search" in snap.tool_execution_time
        assert snap.tool_execution_time["search"] == 100.0

    def test_record_error(self):
        m = MetricsCollector()
        m.record_error()
        snap = m.snapshot()
        assert snap.error_rate["errors"] == 1

    def test_record_iteration(self):
        m = MetricsCollector()
        m.record_iteration()
        m.record_iteration()
        snap = m.snapshot()
        assert snap.agent_iterations == 2

    def test_record_session(self):
        m = MetricsCollector()
        m.record_session()
        snap = m.snapshot()
        assert snap.session_count == 1

    def test_reset(self):
        m = MetricsCollector()
        m.record_tokens(prompt=100)
        m.reset()
        snap = m.snapshot()
        assert snap.token_usage["total"] == 0


class TestTracer:
    def test_start_trace(self):
        t = Tracer()
        trace_id = t.start_trace("test")
        assert trace_id
        assert t.active_trace_id == trace_id

    def test_start_span(self):
        t = Tracer()
        t.start_trace()
        span = t.start_span("tool_execution", category="tool")
        assert span.name == "tool_execution"
        assert span.category == "tool"

    def test_end_span(self):
        t = Tracer()
        t.start_trace()
        span = t.start_span("test")
        t.end_span(span)
        assert span.end_time > 0
        assert span.duration_ms >= 0

    def test_get_spans(self):
        t = Tracer()
        tid = t.start_trace()
        t.start_span("op1")
        t.start_span("op2")
        spans = t.get_spans(tid)
        assert len(spans) == 3  # trace + op1 + op2

    def test_clear(self):
        t = Tracer()
        t.start_trace()
        t.clear()
        assert t.get_spans() == []

    def test_end_trace(self):
        t = Tracer()
        t.start_trace()
        t.start_span("op")
        t.end_trace()
        assert t.active_trace_id == ""


class TestSpan:
    def test_create(self):
        span = Span(name="test")
        assert span.name == "test"
        assert span.span_id
        assert span.trace_id
        assert span.start_time > 0

    def test_duration(self):
        span = Span(name="test")
        span.close()
        assert span.duration_ms >= 0

    def test_to_dict(self):
        span = Span(name="test", category="tool", error="fail")
        span.close()
        d = span.to_dict()
        assert d["name"] == "test"
        assert d["category"] == "tool"
        assert d["error"] == "fail"
        assert d["duration_ms"] >= 0


class TestHealthCheck:
    def test_initial_status(self):
        hc = HealthCheck()
        status = hc.get_status()
        assert status.status == "ok"
        assert status.uptime_seconds >= 0

    def test_register_component(self):
        hc = HealthCheck()
        hc.register_component("graph", "ok")
        hc.register_component("memory", "ok")
        status = hc.get_status()
        assert "graph" in status.components
        assert "memory" in status.components

    def test_component_degraded(self):
        hc = HealthCheck()
        hc.register_component("db", "error")
        status = hc.get_status()
        assert status.status == "error"

    def test_record_error(self):
        hc = HealthCheck()
        hc.record_error()
        status = hc.get_status()
        assert status.errors_last_minute >= 1

    def test_active_sessions(self):
        hc = HealthCheck()
        hc.set_active_sessions(5)
        status = hc.get_status()
        assert status.active_sessions == 5


class TestDebugMode:
    def test_enable_disable(self):
        d = DebugMode()
        assert d.enabled is False
        d.enable()
        assert d.enabled is True
        d.disable()
        assert d.enabled is False

    def test_capture(self):
        d = DebugMode()
        d.enable()
        snap = d.capture("agent_node", {"key": "value"})
        assert snap is not None
        assert snap.node == "agent_node"
        assert snap.state["key"] == "value"

    def test_capture_when_disabled(self):
        d = DebugMode()
        snap = d.capture("node", {})
        assert snap is None

    def test_clear(self):
        d = DebugMode()
        d.enable()
        d.capture("node", {})
        d.clear()
        assert len(d.snapshots) == 0

    def test_summary(self):
        d = DebugMode()
        d.enable()
        d.capture("node_a", {"k": "v"})
        d.capture("node_b", {})
        summary = d.summary()
        assert "node_a" in summary
        assert "node_b" in summary


# ═══════════════════════════════════════════════════════════════════════
# Task 6.5: Gateway Integration
# ═══════════════════════════════════════════════════════════════════════


class TestGatewayEventType:
    def test_classify_content(self):
        assert classify_chunk(StreamChunk(content="hi")) == GatewayEventType.CONTENT

    def test_classify_reasoning(self):
        assert classify_chunk(StreamChunk(reasoning="think")) == GatewayEventType.REASONING

    def test_classify_tool_calls(self):
        assert classify_chunk(StreamChunk(tool_calls=[ToolCallDelta()])) == GatewayEventType.TOOL_CALL

    def test_classify_finish(self):
        assert classify_chunk(StreamChunk(finish_reason="stop")) == GatewayEventType.FINISH

    def test_classify_error(self):
        assert classify_chunk(StreamChunk(meta={"error": "fail"})) == GatewayEventType.ERROR

    def test_classify_empty(self):
        chunk = StreamChunk()
        assert classify_chunk(chunk) == GatewayEventType.CONTENT


class TestGatewayConfig:
    def test_defaults(self):
        config = GatewayConfig()
        assert config.url == ""
        assert config.max_retries == 3
        assert config.max_queue_size == 1000

    def test_custom(self):
        config = GatewayConfig(url="http://example.com", api_key="key123", batch_size=10)
        assert config.url == "http://example.com"
        assert config.api_key == "key123"
        assert config.batch_size == 10


class TestBackpressureController:
    def test_block_strategy(self):
        bp = BackpressureController(strategy="block", max_queue_size=5)
        assert bp.check(3) is True

    def test_drop_strategy(self):
        bp = BackpressureController(strategy="drop", max_queue_size=1)
        assert bp.check(0) is True
        assert bp.check(5) is False
        assert bp.dropped_count == 1

    def test_throttle_strategy(self):
        bp = BackpressureController(strategy="throttle", max_queue_size=1)
        assert bp.check(5) is True  # throttles but accepts


class TestBatchBuffer:
    def test_buffer_until_max_size(self):
        buf = BatchBuffer(max_size=3, max_interval_ms=10000)
        assert buf.add(StreamChunk(content="a")) is None
        assert buf.add(StreamChunk(content="b")) is None
        batch = buf.add(StreamChunk(content="c"))
        assert batch is not None
        assert len(batch) == 3

    def test_flush(self):
        buf = BatchBuffer(max_size=10, max_interval_ms=10000)
        buf.add(StreamChunk(content="a"))
        batch = buf.flush()
        assert batch is not None
        assert len(batch) == 1

    def test_flush_empty(self):
        buf = BatchBuffer()
        assert buf.flush() is None


class TestGatewayManager:
    def test_init(self):
        gm = GatewayManager()
        assert gm.sent_count == 0

    def test_connect_http(self):
        gm = GatewayManager()
        gw = gm.connect_http("http://example.com", "key123")
        assert isinstance(gw, HTTPGateway)

    def test_connect_ws(self):
        gm = GatewayManager()
        gw = gm.connect_ws("ws://example.com")
        assert isinstance(gw, WebSocketGateway)

    def test_create_consumer(self):
        gm = GatewayManager()
        consumer = gm.create_consumer()
        assert callable(consumer)

    def test_send_without_connection(self):
        gm = GatewayManager()
        import asyncio
        result = asyncio.run(gm.send_chunk(StreamChunk(content="test")))
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])