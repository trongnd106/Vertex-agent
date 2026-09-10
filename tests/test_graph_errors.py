"""Tests for ``src.graph.errors`` — error handling and retry."""

import time

import pytest

from src.graph.errors import (
    ChannelError,
    CompilationError,
    GraphError,
    MaxRetriesExceeded,
    NodeExecutionError,
    RetryPolicy,
    RetryableNode,
    compute_backoff,
    get_error_handlers,
    register_error_handler,
    run_error_handlers,
    should_retry,
    unregister_error_handler,
    with_retry,
)


class TestGraphError:
    def test_base_error(self):
        """GraphError has default attributes."""
        err = GraphError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.node is None
        assert err.step is None
        assert err.recoverable is True

    def test_error_with_node(self):
        """GraphError can specify the failing node."""
        err = GraphError("fail", node="processor", step=3)
        assert err.node == "processor"
        assert err.step == 3

    def test_non_recoverable_error(self):
        """Some errors are not recoverable."""
        err = GraphError("fatal", recoverable=False)
        assert err.recoverable is False

    def test_node_execution_error(self):
        """NodeExecutionError is a GraphError."""
        err = NodeExecutionError("node crashed", node="worker")
        assert isinstance(err, GraphError)
        assert err.node == "worker"

    def test_channel_error(self):
        """ChannelError is a GraphError."""
        err = ChannelError("channel update failed")
        assert isinstance(err, GraphError)

    def test_compilation_error_is_non_recoverable(self):
        """CompilationError is always non-recoverable."""
        err = CompilationError("invalid schema")
        assert err.recoverable is False


class TestRetryPolicy:
    def test_defaults(self):
        policy = RetryPolicy()
        assert policy.max_attempts == 3

    def test_compute_backoff(self):
        policy = RetryPolicy(jitter=False)
        delay = compute_backoff(policy, 0)
        assert delay == 0.5  # initial_interval * 2^0

    def test_backoff_increases(self):
        policy = RetryPolicy(jitter=False)
        delay_0 = compute_backoff(policy, 0)
        delay_1 = compute_backoff(policy, 1)
        assert delay_1 > delay_0

    def test_backoff_capped(self):
        policy = RetryPolicy(jitter=False, max_interval=2.0)
        delay = compute_backoff(policy, 10)
        assert delay <= 2.0

    def test_jitter_returns_different_values(self):
        policy = RetryPolicy(jitter=True)
        delays = {compute_backoff(policy, 0) for _ in range(10)}
        # With jitter, we expect variation
        assert len(delays) > 1


class TestShouldRetry:
    def test_retry_on_base_exception(self):
        policy = RetryPolicy(retry_on=(ValueError,))
        assert should_retry(policy, ValueError("bad value"))
        assert not should_retry(policy, TypeError("bad type"))

    def test_default_retries_on_any(self):
        policy = RetryPolicy()
        assert should_retry(policy, RuntimeError("any error"))


class TestWithRetry:
    def test_no_retry_on_success(self):
        """Function succeeds on first try, no retry needed."""

        call_count = 0

        @with_retry(max_attempts=3)
        def succeed(state):
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeed({})
        assert result == "ok"
        assert call_count == 1

    def test_retry_on_failure_then_succeed(self):
        """Function fails once then succeeds."""

        call_count = 0

        @with_retry(max_attempts=3, initial_interval=0.01, jitter=False)
        def flaky(state):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("transient failure")
            return "recovered"

        result = flaky({})
        assert result == "recovered"
        assert call_count == 2

    def test_exhaust_retries(self):
        """All retries exhausted, exception propagates."""

        call_count = 0

        @with_retry(max_attempts=2, initial_interval=0.01, jitter=False)
        def always_fails(state):
            nonlocal call_count
            call_count += 1
            raise ValueError("persistent failure")

        with pytest.raises(MaxRetriesExceeded):
            always_fails({})
        assert call_count == 2


class TestRetryableNode:
    def test_execute_success(self):
        node = RetryableNode(lambda s: {"result": "ok"}, node_name="test")
        result = node.execute({})
        assert result == {"result": "ok"}

    def test_execute_failure(self):
        node = RetryableNode(
            lambda s: (_ for _ in ()).throw(ValueError("fail")),  # raises
            policy=RetryPolicy(max_attempts=1),
            node_name="failing",
        )
        with pytest.raises(ValueError, match="fail"):
            node.execute({})


class TestErrorHandlerRegistry:
    def setup_method(self):
        from src.graph.errors import clear_error_handlers
        clear_error_handlers()

    def test_register_and_run(self):
        """Error handlers can be registered and executed."""

        handled: list[str] = []

        def handler(state, exc):
            handled.append(str(exc))
            return {"error_handled": True}

        register_error_handler("test_node", handler)
        state = {"key": "val"}
        exc = ValueError("test error")
        result = run_error_handlers("test_node", state, exc)

        assert len(handled) == 1
        assert result == {"error_handled": True}

    def test_unregister(self):
        """Error handlers can be unregistered."""

        def handler(state, exc):
            return None

        register_error_handler("test_node", handler)
        assert len(get_error_handlers("test_node")) == 1
        unregister_error_handler("test_node", handler)
        assert len(get_error_handlers("test_node")) == 0

    def test_handler_exception_does_not_propagate(self):
        """An error in the error handler is caught silently."""

        def broken_handler(state, exc):
            raise RuntimeError("handler crashed")

        register_error_handler("test_node", broken_handler)
        # Should not raise
        result = run_error_handlers("test_node", {}, ValueError("orig"))
        assert result is None

    def test_no_handlers(self):
        """Running handlers on a node with none registered returns None."""
        result = run_error_handlers("unknown_node", {}, ValueError("x"))
        assert result is None