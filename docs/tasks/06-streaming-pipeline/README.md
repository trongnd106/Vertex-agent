# Streaming & Observability

> **Nguồn tham khảo:** orchestrator `streaming/` (chunks, transport, producers, formatters); LangGraph `stream/` (stream_channel, _mux, run_stream); DeepAgents streaming patterns; LangSmith tracing

## Mục tiêu

Xây dựng streaming pipeline cho real-time agent output và observability system cho tracing, monitoring, và debugging.

## Tasks

### Task 6.1: StreamChunk Schema & Producers

**Mô tả:** Implement StreamChunk schema và các producers cho different LLM sources.

**File tham khảo:**
- orchestrator: `streaming/chunks.py` (StreamChunk, ToolCallDelta, ToolResult)
- `streaming/producers/langgraph_agent.py` (LangGraphProducer)
- LangGraph: `stream/stream_channel.py`, `stream/_types.py`

**Yêu cầu:**
- StreamChunk dataclass:
  - `content`: str | None — text content delta
  - `reasoning`: str | None — reasoning/thinking delta
  - `tool_calls`: list[ToolCallDelta] — tool call fragments
  - `tool_result`: ToolResult | None — tool execution result
  - `finish_reason`: str | None — "stop" | "length" | "tool_calls" | "cancelled"
  - `id`, `model`, `node_name`, `extra`, `raw`, `meta`
- Producers:
  - **LangGraphProducer**: `CompiledStateGraph.astream()` -> StreamChunk
  - **OpenAIProducer**: `OpenAI.chat.completions.create(stream=True)` -> StreamChunk
  - **Simulator**: fake data cho testing

### Task 6.2: Stream Transport Layer

**Mô tả:** Implement transport layer: forward chunks từ producer tới formatter/gateway.

**File tham khảo:**
- orchestrator: `streaming/transport.py` (StreamTransport), `streaming/retry.py` (RetryPolicy), `streaming/cancellation.py` (CancelToken)

**Yêu cầu:**
- StreamTransport: forward chunks với retry
- Tee: ghi ra collector + debug file cùng lúc
- RetryPolicy:
  - `max_attempts`: số lần retry
  - `initial_backoff`, `max_backoff`: exponential backoff
  - `retry_statuses`: {429, 502, 503, 504}
  - `allow_midstream_replay`: cho phép replay khi midstream failure
  - `max_replay_bytes`: 2MB replay buffer
- CancelToken: hủy streaming khi cần
- StreamCollector: collect chunks cho debug
- FileDebugPrinter: ghi debug trace ra file

### Task 6.3: Stream Formatters

**Mô tả:** Implement formatters: convert StreamChunks sang output formats.

**File tham khảo:**
- orchestrator: `streaming/formatters/` (chatbox.py, openai.py, claude.py, base.py, factory.py)

**Yêu cầu:**
- StreamFormatter base class
- Formatters:
  - **ChatboxFormatter**: NDJSON format cho production
  - **OpenAIFormatter**: SSE hoặc NDJSON (OpenAI Chat Completions format)
  - **ClaudeFormatter**: SSE block-based (text_delta, thinking_delta, tool_use, tool_result)
- Format features:
  - Reasoning extraction riêng
  - Tool call / tool result rendering
  - Text content delta streaming
  - Finish reason broadcast
- FormatterFactory: tạo formatter dựa trên config

### Task 6.4: Observability & Tracing

**Mô tả:** Implement observability system: tracing, metrics, và monitoring.

**File tham khảo:**
- Vertex-agent: `docs/runbook-observability.md` (LangSmith tracing)
- LangSmith: LangChainTracer, tracing_v2_enabled
- orchestrator: Langfuse integration
- LangGraph: callbacks, debug mode

**Yêu cầu:**
- LangSmith tracing: automatic tracing qua environment variables
- Custom tracing: thêm spans cho tool execution, middleware, subagents
- Metrics:
  - Token usage per turn/session
  - Tool execution time
  - Streaming latency (end-to-end)
  - Error rate by component
  - Agent iteration count
- Logging: structured logging cho mọi agent operation
- Health check: agent health endpoints
- Debug mode: step-by-step execution trace với state snapshots

### Task 6.5: Gateway Integration

**Mô tả:** Xây dựng gateway integration cho real-time UI communication.

**File tham khảo:**
- orchestrator: Gateway pattern (POST /api/receive-stream-v2)
- `stream/gw_stream.py` (ChatboxGateway)

**Yêu cầu:**
- HTTP gateway: POST chunks tới gateway endpoint
- WebSocket gateway: real-time WebSocket push
- Event types: reasoning, content, tool_call, tool_result, error, finish
- Reconnection: tự động reconnect khi mất kết nối
- Backpressure: flow control khi gateway chậm
- Batch: batch chunks cho efficiency
- Security: authentication/authorization cho gateway calls