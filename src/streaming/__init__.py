"""Streaming & observability package.

Provides real-time streaming pipeline, transport, formatters,
observability (metrics, tracing, health), and gateway integration
for UI communication.

Subpackages:
    producers     — StreamChunk schema, LLM producers (LangGraph, OpenAI, Simulated)
    transport     — Transport layer (retry, cancellation, tee, collectors)
    formatters    — Output formatters (Chatbox NDJSON, OpenAI SSE, Claude SSE)
    observability — Metrics, tracing, structured logging, health checks, debug mode
    gateway       — HTTP/WebSocket gateway for UI communication

Usage:
    from src.streaming import StreamChunk, StreamProducer
    from src.streaming import StreamTransport, Tee, CancelToken
    from src.streaming import ChatboxFormatter, FormatterFactory
    from src.streaming import MetricsCollector, Tracer, HealthCheck
    from src.streaming import GatewayManager, GatewayConfig
"""

from src.streaming.producers import (
    LangGraphProducer,
    OpenAIProducer,
    SimulatedProducer,
    StreamChunk,
    StreamProducer,
    ToolCallDelta,
)
from src.streaming.transport import (
    CancelToken,
    CancelledError,
    FileDebugPrinter,
    RetryPolicy,
    StreamCollector,
    StreamConsumer,
    StreamTransport,
    Tee,
)
from src.streaming.formatters import (
    ChatboxFormatter,
    ClaudeFormatter,
    FormatterFactory,
    OpenAIFormatter,
    StreamFormatter,
)
from src.streaming.execution_log import (
    ExecutionLogger,
    ExecutionRun,
    ExecutionStep,
    StepStatus,
)
from src.streaming.observability import (
    DebugMode,
    DebugSnapshot,
    HealthCheck,
    HealthStatus,
    MetricsCollector,
    MetricSnapshot,
    Span,
    StructuredLogger,
    Tracer,
)
from src.streaming.gateway import (
    BackpressureController,
    BatchBuffer,
    GatewayConfig,
    GatewayEventType,
    GatewayManager,
    HTTPGateway,
    WebSocketGateway,
    classify_chunk,
)

__all__ = [
    # producers
    "LangGraphProducer",
    "OpenAIProducer",
    "SimulatedProducer",
    "StreamChunk",
    "StreamProducer",
    "ToolCallDelta",
    # transport
    "CancelToken",
    "CancelledError",
    "FileDebugPrinter",
    "RetryPolicy",
    "StreamCollector",
    "StreamConsumer",
    "StreamTransport",
    "Tee",
    # formatters
    "ChatboxFormatter",
    "ClaudeFormatter",
    "FormatterFactory",
    "OpenAIFormatter",
    "StreamFormatter",
    # observability
    "DebugMode",
    "DebugSnapshot",
    "HealthCheck",
    "HealthStatus",
    "MetricsCollector",
    "MetricSnapshot",
    "Span",
    "StructuredLogger",
    "Tracer",
    # execution log
    "ExecutionLogger",
    "ExecutionRun",
    "ExecutionStep",
    "StepStatus",
    # gateway
    "BackpressureController",
    "BatchBuffer",
    "GatewayConfig",
    "GatewayEventType",
    "GatewayManager",
    "HTTPGateway",
    "WebSocketGateway",
    "classify_chunk",
]