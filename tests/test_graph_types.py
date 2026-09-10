"""Tests for ``src.graph.types`` — core types and data structures."""

from src.graph.types import (
    BaseChannel,
    Command,
    Interrupt,
    RetryPolicy,
    Send,
    StreamChunk,
    StreamMode,
)


def test_send_creation():
    """Send can be created with node and state."""
    s = Send(node="processor", state={"key": "value"})
    assert s.node == "processor"
    assert s.state == {"key": "value"}


def test_send_is_frozen():
    """Send is immutable (frozen dataclass)."""
    s = Send(node="n", state={})
    with pytest.raises(AttributeError):
        s.node = "other"  # type: ignore[misc]  # noqa


def test_command_defaults():
    """Command has sensible defaults when no args provided."""
    c = Command()
    assert c.goto is None
    assert c.update is None
    assert c.resume is None


def test_command_with_goto():
    """Command can specify a target node."""
    c = Command(goto="next_node")
    assert c.goto == "next_node"


def test_command_with_update():
    """Command can carry state updates."""
    c = Command(update={"key": "value"})
    assert c.update == {"key": "value"}


def test_command_with_send():
    """Command goto can be a Send for dynamic routing."""
    s = Send(node="worker", state={"task": "process"})
    c = Command(goto=s)
    assert isinstance(c.goto, Send)
    assert c.goto.node == "worker"  # type: ignore[union-attr]


def test_interrupt_creation():
    """Interrupt stores value, node, and step."""
    intr = Interrupt(value="need_approval", node="human_in_loop", step=3)
    assert intr.value == "need_approval"
    assert intr.node == "human_in_loop"
    assert intr.step == 3


def test_stream_chunk_defaults():
    """StreamChunk has sensible defaults."""
    chunk = StreamChunk()
    assert chunk.content is None
    assert chunk.reasoning is None
    assert chunk.tool_calls == []
    assert chunk.tool_result is None
    assert chunk.finish_reason is None


def test_stream_chunk_with_content():
    """StreamChunk can carry text content."""
    chunk = StreamChunk(content="Hello", node_name="agent", step=1)
    assert chunk.content == "Hello"
    assert chunk.node_name == "agent"
    assert chunk.step == 1


def test_retry_policy_defaults():
    """RetryPolicy has sensible defaults."""
    policy = RetryPolicy()
    assert policy.max_attempts == 3
    assert policy.initial_interval == 0.5
    assert policy.max_interval == 60.0
    assert policy.backoff_factor == 2.0


def test_retry_policy_custom():
    """RetryPolicy can be customised."""
    policy = RetryPolicy(max_attempts=5, initial_interval=1.0, jitter=False)
    assert policy.max_attempts == 5
    assert policy.initial_interval == 1.0
    assert not policy.jitter


def test_stream_mode_values():
    """StreamMode enum has expected values."""
    assert StreamMode.VALUES.value == "values"
    assert StreamMode.UPDATES.value == "updates"
    assert StreamMode.MESSAGES.value == "messages"
    assert StreamMode.EVENTS.value == "events"
    assert StreamMode.DEBUG.value == "debug"


# Import pytest for proper error handling
import pytest  # noqa: E402 (imported at end for readability above)