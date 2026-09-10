"""Tests for Routing & Control Flow (Task 7)."""

import asyncio
import time
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.routing.conditional import (
    BranchSpec,
    ConditionalRouter,
    DynamicRouter,
    MapReduceRouter,
    PathMap,
    RouteCondition,
)
from src.routing.events import (
    CentralizedErrorHandler,
    CircuitBreaker,
    CircuitState,
    ErrorCategory,
    ErrorClassifier,
    ErrorResponse,
    ErrorSeverity,
    EventBus,
    EventType,
    MessageQueueEventProducer,
    RetryHandler,
    SystemEvent,
)
from src.routing.hitl import (
    ApprovalFlow,
    HumanInTheLoopMiddleware,
    InputCollector,
    InterruptReason,
    InterruptSignal,
    ResumeSignal,
)
from src.routing.loops import (
    ForLoop,
    LoopAction,
    LoopController,
    LoopDetector,
    MapLoop,
    NestedLoop,
    RecursionLimit,
    WhileLoop,
)
from src.routing.workflow import (
    HandlerRegistry,
    Task,
    TaskDispatcher,
    TaskResult,
    TaskStatus,
    TaskTree,
    Workflow,
    WorkflowResult,
    WorkflowStep,
    WorkflowStepStatus,
)


# ======================================================================
# 7.1 — Conditional & Dynamic Routing
# ======================================================================


class TestRouteCondition:
    def test_route_fn_returns_target(self):
        cond = RouteCondition(
            name="greeting",
            description="Matches greeting states",
            route_fn=lambda s: "greeter" if "hello" in str(s.get("input", "")) else "",
            priority=1,
        )
        assert cond.name == "greeting"
        assert cond.description == "Matches greeting states"
        assert cond.priority == 1


class TestConditionalRouter:
    def test_route_to_first_match(self):
        router = ConditionalRouter()
        router.add_condition(
            RouteCondition(
                name="greeting",
                route_fn=lambda s: "greeter" if s.get("type") == "greeting" else "",
            )
        )
        router.add_condition(
            RouteCondition(
                name="farewell",
                route_fn=lambda s: "farewell" if s.get("type") == "farewell" else "",
            )
        )
        assert router.route({"type": "greeting"}) == "greeter"
        assert router.route({"type": "farewell"}) == "farewell"

    def test_no_match_raises(self):
        router = ConditionalRouter()
        with pytest.raises(Exception):
            router.route({"type": "unknown"})

    def test_route_with_default(self):
        router = ConditionalRouter()
        assert router.route_with_default({"x": 1}, default="fallback") == "fallback"

    def test_priority_order(self):
        router = ConditionalRouter()
        router.add_condition(
            RouteCondition(name="catch-all", route_fn=lambda s: "catch-all", priority=0)
        )
        router.add_condition(
            RouteCondition(
                name="urgent",
                route_fn=lambda s: "urgent" if s.get("type") == "urgent" else "",
                priority=10,
            )
        )
        # Higher priority evaluated first
        assert router.route({"type": "urgent"}) == "urgent"

    def test_conditions_property(self):
        router = ConditionalRouter()
        c1 = RouteCondition(name="c1", route_fn=lambda s: "")
        c2 = RouteCondition(name="c2", route_fn=lambda s: "")
        router.add_condition(c1)
        router.add_condition(c2)
        assert len(router.conditions) == 2

    def test_init_with_conditions(self):
        c1 = RouteCondition(name="c1", route_fn=lambda s: "n1")
        router = ConditionalRouter(conditions=[c1])
        assert len(router.conditions) == 1


class TestPathMap:
    def test_resolve(self):
        pm = PathMap(routes={"weather": "weather_node", "news": "news_node"})
        assert pm.resolve("weather") == "weather_node"
        assert pm.resolve("news") == "news_node"

    def test_default_when_not_found(self):
        pm = PathMap(routes={"a": "node_a"}, default="__end__")
        assert pm.resolve("unknown") == "__end__"

    def test_custom_default(self):
        pm = PathMap(routes={}, default="fallback")
        assert pm.resolve("anything") == "fallback"

    def test_empty_routes(self):
        pm = PathMap()
        assert pm.resolve("x") == "__end__"


class TestDynamicRouter:
    def test_route_finds_target(self):
        router = DynamicRouter()
        from src.routing.conditional import DynamicRoute

        router.add_route(
            DynamicRoute(
                name="high-value",
                target="process_high",
                condition_fn=lambda s: s.get("value", 0) > 100,
            )
        )
        router.add_route(
            DynamicRoute(
                name="low-value",
                target="process_low",
                condition_fn=lambda s: s.get("value", 0) <= 100,
            )
        )
        assert router.route({"value": 200}) == "process_high"
        assert router.route({"value": 50}) == "process_low"

    def test_route_default_on_no_match(self):
        router = DynamicRouter()
        from src.routing.conditional import DynamicRoute

        router.add_route(
            DynamicRoute(
                name="only-match",
                target="target",
                condition_fn=lambda s: s.get("x") == "special",
            )
        )
        assert router.route({"x": "other"}, default="__end__") == "__end__"

    def test_find_target_returns_none(self):
        router = DynamicRouter()
        assert router.find_target({"x": 1}) is None

    def test_route_all(self):
        router = DynamicRouter()
        from src.routing.conditional import DynamicRoute

        router.add_route(
            DynamicRoute(
                name="r1",
                target="t1",
                condition_fn=lambda s: s.get("a") > 0,
            )
        )
        router.add_route(
            DynamicRoute(
                name="r2",
                target="t2",
                condition_fn=lambda s: s.get("b") > 0,
            )
        )
        matches = router.route_all({"a": 1, "b": 2})
        assert len(matches) == 2

    def test_route_all_partial(self):
        router = DynamicRouter()
        from src.routing.conditional import DynamicRoute

        router.add_route(
            DynamicRoute(
                name="r1",
                target="t1",
                condition_fn=lambda s: s.get("x") > 0,
            )
        )
        router.add_route(
            DynamicRoute(
                name="r2",
                target="t2",
                condition_fn=lambda s: s.get("y") > 0,
            )
        )
        matches = router.route_all({"x": 1, "y": 0})
        assert len(matches) == 1

    def test_to_send(self):
        router = DynamicRouter()
        from src.routing.conditional import DynamicRoute

        router.add_route(
            DynamicRoute(
                name="r1",
                target="node_a",
                condition_fn=lambda s: True,
            )
        )
        sends = router.to_send({"key": "val"})
        assert len(sends) == 1
        # Send has .node and .arg (not .state) in langgraph
        assert sends[0].node == "node_a"

    def test_to_send_with_input_fn(self):
        router = DynamicRouter()
        from src.routing.conditional import DynamicRoute

        router.add_route(
            DynamicRoute(
                name="r1",
                target="node_a",
                condition_fn=lambda s: True,
            )
        )
        sends = router.to_send({"key": "val"}, input_fn=lambda s: {"transformed": s["key"]})
        assert sends[0].arg == {"transformed": "val"}


class TestMapReduceRouter:
    def test_fan_out_distributes_items(self):
        router = MapReduceRouter(map_node="map", reduce_node="reduce", worker_nodes=["w1", "w2"])
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        sends = router.fan_out(items, input_fn=lambda item: {"data": item})
        assert len(sends) == 3
        for s in sends:
            assert s.node in ("w1", "w2")
            assert "data" in s.arg

    def test_fan_out_empty_items(self):
        router = MapReduceRouter(map_node="m", reduce_node="r", worker_nodes=["w1"])
        assert router.fan_out([], input_fn=lambda x: {}) == []

    def test_fan_out_no_workers(self):
        router = MapReduceRouter(map_node="m", reduce_node="r")
        assert router.fan_out([1, 2], input_fn=lambda x: {}) == []

    def test_fan_all(self):
        router = MapReduceRouter(map_node="m", reduce_node="r", worker_nodes=["w1", "w2"])
        sends = router.fan_all({"x": 1})
        assert len(sends) == 2
        assert sends[0].node == "w1"
        assert sends[1].node == "w2"

    def test_properties(self):
        router = MapReduceRouter(map_node="map", reduce_node="reduce", worker_nodes=["w1"])
        assert router.map_node == "map"
        assert router.reduce_node == "reduce"
        assert router.worker_nodes == ["w1"]

    def test_add_worker(self):
        router = MapReduceRouter(map_node="m", reduce_node="r")
        router.add_worker("w1")
        router.add_worker("w2")
        assert router.worker_nodes == ["w1", "w2"]

    def test_branch_spec_defaults(self):
        spec = BranchSpec()
        assert spec.path_fn is None
        assert spec.path_map == {}

    def test_branch_spec_resolve(self):
        spec = BranchSpec(
            path_fn=lambda s: "action_a" if s.get("x") > 5 else "action_b",
            path_map={"action_a": "node_a", "action_b": "node_b"},
        )
        assert spec.resolve({"x": 10}) == "node_a"
        assert spec.resolve({"x": 1}) == "node_b"

    def test_branch_spec_resolve_no_match(self):
        spec = BranchSpec(
            path_fn=lambda s: "unknown",
            path_map={"action_a": "node_a"},
        )
        assert spec.resolve({}) == "__end__"

    def test_branch_spec_with_condition(self):
        spec = BranchSpec(
            path_fn=lambda s: "action_a",
            path_map={"action_a": "node_a"},
            condition=lambda s: s.get("enabled", False),
        )
        assert spec.resolve({"enabled": True}) == "node_a"
        assert spec.resolve({"enabled": False}) == "__end__"

    def test_branch_spec_to_path_map(self):
        spec = BranchSpec(path_map={"a": "b"})
        assert spec.to_path_map() == {"a": "b"}


# ======================================================================
# 7.2 — Loops & Recursion
# ======================================================================


class TestLoopController:
    def test_break(self):
        ctrl = LoopController()
        ctrl.break_loop()
        assert ctrl.check() == LoopAction.BREAK

    def test_continue(self):
        ctrl = LoopController()
        ctrl.continue_loop()
        assert ctrl.check() == LoopAction.CONTINUE

    def test_exit(self):
        ctrl = LoopController()
        ctrl.exit_all()
        assert ctrl.check() == LoopAction.EXIT

    def test_check_consumes_action(self):
        ctrl = LoopController()
        ctrl.break_loop()
        ctrl.check()  # consume
        assert ctrl.check() == LoopAction.NONE  # now empty

    def test_is_break(self):
        ctrl = LoopController()
        ctrl.break_loop()
        assert ctrl.is_break is True

    def test_is_break_false(self):
        ctrl = LoopController()
        assert ctrl.is_break is False

    def test_action_values(self):
        assert LoopAction.BREAK.value == "break"
        assert LoopAction.CONTINUE.value == "continue"
        assert LoopAction.EXIT.value == "exit"
        assert LoopAction.NONE.value == "none"


class TestForLoop:
    def test_run_basic(self):
        results = []

        def body_fn(state, i):
            results.append(i)
            return state

        loop = ForLoop(iterations=3, body_fn=body_fn)
        loop.run({"x": 0})
        assert results == [0, 1, 2]

    def test_run_returns_updated_state(self):
        loop = ForLoop(iterations=2, body_fn=lambda s, i: {"count": s.get("count", 0) + 1})
        final = loop.run({"count": 0})
        assert final["count"] == 2

    def test_properties(self):
        loop = ForLoop(iterations=5, body_fn=lambda s, i: s, name="test-loop")
        assert loop.iterations == 5
        assert loop.name == "test-loop"
        assert loop.controller is not None

    def test_break_via_controller(self):
        loop = ForLoop(iterations=100, body_fn=lambda s, i: s)
        loop.controller.break_loop()
        final = loop.run({"x": 0})
        # Breaks immediately
        assert final is not None


class TestWhileLoop:
    def test_run_basic(self):
        counter = {"val": 0}

        def cond_fn(state):
            return state["val"] < 3

        def body_fn(state, i):
            state["val"] += 1
            return state

        loop = WhileLoop(condition_fn=cond_fn, body_fn=body_fn)
        final = loop.run(counter)
        assert final["val"] >= 3

    def test_max_iterations(self):
        loop = WhileLoop(
            condition_fn=lambda s: True,
            body_fn=lambda s, i: s,
            max_iterations=5,
        )
        with pytest.raises(RuntimeError, match="exceeded max iterations"):
            loop.run({})

    def test_controller_break(self):
        loop = WhileLoop(
            condition_fn=lambda s: True,
            body_fn=lambda s, i: s,
            max_iterations=100,
        )
        loop.controller.break_loop()
        final = loop.run({})
        assert final is not None

    def test_properties(self):
        loop = WhileLoop(
            condition_fn=lambda s: True,
            body_fn=lambda s, i: s,
            name="my-while",
        )
        assert loop.name == "my-while"
        assert loop.controller is not None


class TestMapLoop:
    def test_run(self):
        items = [1, 2, 3]

        def items_fn(state):
            return items

        def body_fn(item, i, state):
            return {"result": item * 2}

        loop = MapLoop(items_fn=items_fn, body_fn=body_fn)
        results = loop.run({"items": items})
        assert len(results) == 3
        assert results[0]["result"] == 2
        assert results[1]["result"] == 4
        assert results[2]["result"] == 6

    def test_run_empty(self):
        loop = MapLoop(items_fn=lambda s: [], body_fn=lambda item, i, s: {})
        assert loop.run({}) == []

    def test_properties(self):
        loop = MapLoop(items_fn=lambda s: [], body_fn=lambda item, i, s: {}, name="my-map")
        assert loop.name == "my-map"


class TestNestedLoop:
    def test_run_empty(self):
        nested = NestedLoop(name="nested")
        result = nested.run({})
        assert result is not None

    def test_add_loop(self):
        nested = NestedLoop()
        inner = ForLoop(iterations=2, body_fn=lambda s, i: s)
        nested.add_loop(inner)
        assert nested._loops == [inner]

    def test_set_parent(self):
        nested = NestedLoop()
        ctrl = LoopController()
        nested.set_parent(ctrl)
        assert nested._parent_controller is ctrl

    def test_run_with_for_loop(self):
        nested = NestedLoop()
        inner = ForLoop(iterations=2, body_fn=lambda s, i: {"val": s.get("val", 0) + 1})
        nested.add_loop(inner)
        result = nested.run({"val": 0})
        assert result["val"] == 2


class TestRecursionLimit:
    def test_increment(self):
        limit = RecursionLimit(max_steps=3)
        assert limit.increment() == 1
        assert limit.increment() == 2
        assert limit.increment() == 3

    def test_exceeded(self):
        limit = RecursionLimit(max_steps=2)
        limit.increment()
        limit.increment()
        with pytest.raises(Exception):
            limit.increment()

    def test_reset(self):
        limit = RecursionLimit(max_steps=2)
        limit.increment()
        limit.increment()
        with pytest.raises(Exception):
            limit.increment()
        limit.reset()
        assert limit.increment() == 1  # works again

    def test_current(self):
        limit = RecursionLimit(max_steps=10)
        assert limit.current == 0
        limit.increment()
        assert limit.current == 1

    def test_max_steps_property(self):
        limit = RecursionLimit(max_steps=5)
        assert limit.max_steps == 5
        limit.max_steps = 10
        assert limit.max_steps == 10


class TestLoopDetector:
    def test_record_returns_false_first_time(self):
        detector = LoopDetector()
        assert detector.record({"a": 1}) is False

    def test_detect_repeated_state(self):
        detector = LoopDetector()
        state = {"a": 1}
        for _ in range(5):
            result = detector.record(state)
        assert result is True
        assert detector.detected is True

    def test_no_detection_unique_states(self):
        detector = LoopDetector()
        for i in range(10):
            assert detector.record({"a": i}) is False

    def test_reset(self):
        detector = LoopDetector()
        state = {"a": 1}
        for _ in range(6):
            detector.record(state)
        assert detector.detected is True
        detector.reset()
        assert detector.detected is False
        # After reset, first record is clean
        assert detector.record(state) is False

    def test_similarity_threshold(self):
        from src.routing.loops import LoopDetectionConfig

        config = LoopDetectionConfig(
            max_repeated_states=10,
            window_size=10,
            similarity_threshold=0.3,
        )
        detector = LoopDetector(config=config)
        # Record 3 identical states in a window of 10 = 0.3 threshold
        for _ in range(3):
            detector.record({"a": 1})
        # Fill the rest with unique states to get 3/10 = 0.3
        for i in range(7):
            detector.record({"a": i + 100})
        assert detector.detected is True


# ======================================================================
# 7.3 — Human-in-the-Loop
# ======================================================================


class TestInterruptSignal:
    def test_default_fields(self):
        signal = InterruptSignal(reason=InterruptReason.INPUT_REQUIRED)
        assert signal.reason == InterruptReason.INPUT_REQUIRED
        assert signal.interrupt_id != ""
        assert signal.created_at > 0

    def test_custom_interrupt_id(self):
        signal = InterruptSignal(
            reason=InterruptReason.APPROVAL_REQUIRED,
            interrupt_id="custom-123",
        )
        assert signal.interrupt_id == "custom-123"

    def test_to_dict(self):
        signal = InterruptSignal(
            reason=InterruptReason.TOOL_APPROVAL,
            message="Approve?",
            data={"tool": "write"},
        )
        d = signal.to_dict()
        assert d["reason"] == "tool_approval"
        assert d["message"] == "Approve?"
        assert d["data"] == {"tool": "write"}

    def test_allowed_responses(self):
        signal = InterruptSignal(
            reason=InterruptReason.CONFirmation_REQUIRED,
            allowed_responses=["yes", "no"],
        )
        assert signal.allowed_responses == ["yes", "no"]

    def test_timeout(self):
        signal = InterruptSignal(timeout=30.0)
        assert signal.timeout == 30.0


class TestResumeSignal:
    def test_defaults(self):
        signal = ResumeSignal()
        assert signal.interrupt_id == ""
        assert signal.approved is True
        assert signal.response is None

    def test_rejected(self):
        signal = ResumeSignal(interrupt_id="i1", approved=False, response="deny")
        assert signal.approved is False
        assert signal.response == "deny"

    def test_metadata(self):
        signal = ResumeSignal(interrupt_id="i1", metadata={"user": "admin"})
        assert signal.metadata["user"] == "admin"


class TestApprovalFlow:
    def test_request_and_resolve(self):
        flow = ApprovalFlow()
        signal = flow.request_approval(tool_name="write_file", tool_args={"path": "/tmp/x"}, message="Write?")
        assert signal.interrupt_id in str(flow.get_pending())

        resume = flow.resolve(signal.interrupt_id, approved=True)
        assert resume is not None
        assert resume.approved is True
        assert flow.get_pending() == []

    def test_resolve_unknown(self):
        flow = ApprovalFlow()
        assert flow.resolve("nonexistent", True) is None

    def test_rejected_approval(self):
        flow = ApprovalFlow()
        signal = flow.request_approval(tool_name="delete", tool_args={})
        resume = flow.resolve(signal.interrupt_id, approved=False)
        assert resume.approved is False

    def test_check_timeouts(self):
        flow = ApprovalFlow()
        signal = flow.request_approval(
            tool_name="slow_tool",
            tool_args={},
            timeout=0.01,
        )
        time.sleep(0.02)
        resolved = flow.check_timeouts()
        assert len(resolved) == 1
        assert resolved[0].approved is False
        assert resolved[0].metadata.get("reason") == "timeout"

    def test_no_timeout_before_deadline(self):
        flow = ApprovalFlow()
        flow.request_approval(tool_name="t", tool_args={}, timeout=60.0)
        resolved = flow.check_timeouts()
        assert resolved == []

    def test_get_resolved(self):
        flow = ApprovalFlow()
        signal = flow.request_approval(tool_name="t", tool_args={})
        flow.resolve(signal.interrupt_id, True, "ok")
        resume = flow.get_resolved(signal.interrupt_id)
        assert resume is not None
        assert resume.response == "ok"

    def test_get_resolved_none(self):
        flow = ApprovalFlow()
        assert flow.get_resolved("missing") is None


class TestInputCollector:
    def test_request_and_submit(self):
        collector = InputCollector()
        signal = collector.request_input("Enter your name:")
        assert collector.has_pending() is True

        ok = collector.submit_input(signal.interrupt_id, "Alice")
        assert ok is True
        assert collector.has_pending() is False

    def test_get_input(self):
        collector = InputCollector()
        signal = collector.request_input("Enter age:")
        collector.submit_input(signal.interrupt_id, 30)
        assert collector.get_input(signal.interrupt_id) == 30

    def test_get_input_default(self):
        collector = InputCollector()
        assert collector.get_input("missing", default=42) == 42

    def test_submit_unknown(self):
        collector = InputCollector()
        assert collector.submit_input("unknown", "x") is False

    def test_allowed_responses(self):
        collector = InputCollector()
        signal = collector.request_input("Yes or no?", allowed_responses=["yes", "no"])
        assert signal.allowed_responses == ["yes", "no"]


class TestHumanInTheLoopMiddleware:
    def test_needs_approval(self):
        middleware = HumanInTheLoopMiddleware(interrupt_on={"write_file": True})
        assert middleware.needs_approval("write_file") is True
        assert middleware.needs_approval("read_file") is False

    def test_set_interrupt(self):
        middleware = HumanInTheLoopMiddleware()
        middleware.set_interrupt("delete", True)
        assert middleware.needs_approval("delete") is True

    def test_set_interrupt_disable(self):
        middleware = HumanInTheLoopMiddleware(interrupt_on={"write": True})
        middleware.set_interrupt("write", False)
        assert middleware.needs_approval("write") is False

    def test_request_approval_through_middleware(self):
        middleware = HumanInTheLoopMiddleware()
        signal = middleware.request_approval("exec", {"cmd": "ls"})
        assert signal.reason == InterruptReason.TOOL_APPROVAL
        assert signal.data["tool_name"] == "exec"

    def test_approval_flow_property(self):
        middleware = HumanInTheLoopMiddleware()
        assert middleware.approval_flow is not None

    def test_input_collector_property(self):
        middleware = HumanInTheLoopMiddleware()
        assert middleware.input_collector is not None

    @pytest.mark.asyncio
    async def test_before_agent(self):
        middleware = HumanInTheLoopMiddleware()
        await middleware.before_agent({})

    @pytest.mark.asyncio
    async def test_after_agent(self):
        middleware = HumanInTheLoopMiddleware()
        await middleware.after_agent({})

    def test_get_tools(self):
        middleware = HumanInTheLoopMiddleware()
        tools = middleware.get_tools()
        assert len(tools) == 3
        tool_names = [t["name"] for t in tools]
        assert "request_approval" in tool_names
        assert "request_input" in tool_names
        assert "check_approvals" in tool_names


# ======================================================================
# 7.4 — Task Dispatch & Workflow Engine
# ======================================================================


class TestTask:
    def test_task_creation(self):
        task = Task(task_id="t1", task_type="compute", payload={"x": 1})
        assert task.task_id == "t1"
        assert task.task_type == "compute"
        assert task.payload == {"x": 1}
        assert task.created_at > 0

    def test_auto_generate_id(self):
        task = Task(task_type="generic")
        assert task.task_id != ""

    def test_with_parent(self):
        task = Task(task_type="child", payload="data")
        child = task.with_parent("parent-1")
        assert child.parent_id == "parent-1"
        assert child.task_type == "child"

    def test_version_default(self):
        task = Task(task_type="t")
        assert task.version == "1.0.0"

    def test_tags(self):
        task = Task(task_type="t", tags={"urgent", "backend"})
        assert "urgent" in task.tags

    def test_priority(self):
        task = Task(task_type="t", priority=10)
        assert task.priority == 10


class TestTaskResult:
    def test_success(self):
        result = TaskResult(task_id="t1", status=TaskStatus.COMPLETED, output=42)
        assert result.is_success() is True

    def test_failure(self):
        result = TaskResult(task_id="t1", status=TaskStatus.FAILED, error="oops")
        assert result.is_success() is False

    def test_skipped_is_success(self):
        result = TaskResult(task_id="t1", status=TaskStatus.SKIPPED)
        assert result.is_success() is True

    def test_to_dict(self):
        result = TaskResult(task_id="t1", status=TaskStatus.COMPLETED, duration_ms=100.0)
        d = result.to_dict()
        assert d["task_id"] == "t1"
        assert d["status"] == "completed"
        assert d["duration_ms"] == 100.0


class TestHandlerRegistry:
    def test_register_and_resolve(self):
        registry = HandlerRegistry()
        async def handler(task: Task) -> str:
            return f"handled_{task.task_type}"

        registry.register("compute", "1.0.0", handler)
        resolved = registry.resolve("compute")
        assert resolved is handler

    def test_register_latest_version(self):
        registry = HandlerRegistry()
        async def v1(task): return "v1"
        async def v2(task): return "v2"

        registry.register("compute", "1.0.0", v1)
        registry.register("compute", "2.0.0", v2)

        resolved = registry.resolve("compute")
        # Should return the highest version
        assert resolved is v2

    def test_resolve_specific_version(self):
        registry = HandlerRegistry()
        async def v1(task): return "v1"
        async def v2(task): return "v2"

        registry.register("compute", "1.0.0", v1)
        registry.register("compute", "2.0.0", v2)

        resolved = registry.resolve("compute", "1.0.0")
        assert resolved is v1

    def test_resolve_unknown_type(self):
        registry = HandlerRegistry()
        assert registry.resolve("unknown") is None

    def test_resolve_unknown_version(self):
        registry = HandlerRegistry()
        async def h(task): pass
        registry.register("t", "1.0.0", h)
        assert registry.resolve("t", "3.0.0") is None

    def test_unregister(self):
        registry = HandlerRegistry()
        async def h(task): pass
        registry.register("t", "1.0.0", h)
        assert registry.unregister("t", "1.0.0") is True
        assert registry.resolve("t") is None

    def test_unregister_nonexistent(self):
        registry = HandlerRegistry()
        assert registry.unregister("t", "1.0.0") is False

    def test_list_types(self):
        registry = HandlerRegistry()
        async def h1(task): pass
        async def h2(task): pass
        registry.register("a", "1.0.0", h1)
        registry.register("b", "1.0.0", h2)
        types = registry.list_types()
        assert "a" in types
        assert "b" in types

    def test_list_versions(self):
        registry = HandlerRegistry()
        async def h(task): pass
        registry.register("t", "1.0.0", h)
        registry.register("t", "2.0.0", h)
        assert registry.list_versions("t") == ["2.0.0", "1.0.0"]


class TestTaskDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_success(self):
        dispatcher = TaskDispatcher()

        async def handler(task: Task) -> str:
            return f"result_{task.task_id}"

        dispatcher.registry.register("compute", "1.0.0", handler)
        task = Task(task_type="compute")
        result = await dispatcher.dispatch(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.output == f"result_{task.task_id}"

    @pytest.mark.asyncio
    async def test_dispatch_failure(self):
        dispatcher = TaskDispatcher()

        async def handler(task: Task) -> str:
            raise ValueError("handler error")

        dispatcher.registry.register("compute", "1.0.0", handler)
        task = Task(task_type="compute")
        result = await dispatcher.dispatch(task)
        assert result.status == TaskStatus.FAILED
        assert "handler error" in result.error

    @pytest.mark.asyncio
    async def test_dispatch_no_handler(self):
        dispatcher = TaskDispatcher()
        task = Task(task_type="unknown")
        with pytest.raises(ValueError, match="No handler registered"):
            await dispatcher.dispatch(task)

    @pytest.mark.asyncio
    async def test_dispatch_records_history(self):
        dispatcher = TaskDispatcher()
        async def handler(task): return "ok"
        dispatcher.registry.register("t", "1.0.0", handler)
        await dispatcher.dispatch(Task(task_type="t"))
        history = dispatcher.get_history()
        assert len(history) == 1
        assert history[0].status == TaskStatus.COMPLETED

    def test_empty_history(self):
        dispatcher = TaskDispatcher()
        assert dispatcher.get_history() == []


class TestWorkflow:
    @pytest.mark.asyncio
    async def test_single_step(self):
        workflow = Workflow(name="test-wf")

        async def handler(task: Task) -> str:
            return "done"

        workflow.dispatcher.registry.register("compute", "1.0.0", handler)
        workflow.add_step("step1", Task(task_type="compute"))

        result = await workflow.run()
        assert result.overall_status == WorkflowStepStatus.COMPLETED
        assert "step1" in result.step_results
        assert result.step_results["step1"].status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_dependency_order(self):
        workflow = Workflow()

        async def handler_a(task: Task) -> str:
            return "a"

        async def handler_b(task: Task) -> str:
            return "b"

        workflow.dispatcher.registry.register("a", "1.0.0", handler_a)
        workflow.dispatcher.registry.register("b", "1.0.0", handler_b)

        workflow.add_step("step_a", Task(task_type="a"))
        workflow.add_step("step_b", Task(task_type="b"), depends_on=["step_a"])

        result = await workflow.run()
        assert result.step_results["step_a"].status == TaskStatus.COMPLETED
        assert result.step_results["step_b"].status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_duplicate_step_name(self):
        workflow = Workflow()
        workflow.add_step("s1", Task(task_type="t"))
        with pytest.raises(ValueError, match="already exists"):
            workflow.add_step("s1", Task(task_type="t"))

    def test_get_step(self):
        workflow = Workflow()
        workflow.add_step("s1", Task(task_type="t"))
        step = workflow.get_step("s1")
        assert step is not None
        assert step.name == "s1"

    def test_get_step_nonexistent(self):
        workflow = Workflow()
        assert workflow.get_step("missing") is None

    def test_remove_step(self):
        workflow = Workflow()
        workflow.add_step("s1", Task(task_type="t"))
        assert workflow.remove_step("s1") is True
        assert workflow.get_step("s1") is None

    def test_remove_step_with_dependency(self):
        workflow = Workflow()
        workflow.add_step("s1", Task(task_type="t"))
        workflow.add_step("s2", Task(task_type="t"), depends_on=["s1"])
        # Cannot remove s1 because s2 depends on it
        assert workflow.remove_step("s1") is False

    def test_get_ready_steps(self):
        workflow = Workflow()
        workflow.add_step("s1", Task(task_type="t"))
        workflow.add_step("s2", Task(task_type="t"), depends_on=["s1"])
        ready = workflow.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].name == "s1"

    def test_workflow_result_defaults(self):
        result = WorkflowResult()
        assert result.overall_status == WorkflowStepStatus.PENDING
        assert result.duration_ms == 0.0


class TestTaskTree:
    def test_add_task(self):
        tree = TaskTree()
        task = Task(task_type="compute")
        node_id = tree.add_task(task)
        assert node_id == task.task_id

    def test_parent_child(self):
        tree = TaskTree()
        parent = Task(task_type="parent")
        child = Task(task_type="child")
        tree.add_task(parent)
        tree.add_task(child, parent_id=parent.task_id)
        children = tree.get_children(parent.task_id)
        assert child.task_id in children

    def test_path_to_root(self):
        tree = TaskTree()
        root = Task(task_type="root")
        mid = Task(task_type="mid")
        leaf = Task(task_type="leaf")
        tree.add_task(root)
        tree.add_task(mid, parent_id=root.task_id)
        tree.add_task(leaf, parent_id=mid.task_id)
        path = tree.get_path_to_root(leaf.task_id)
        assert len(path) == 3
        assert path[-1] == root.task_id

    def test_depth(self):
        tree = TaskTree()
        root = Task(task_type="root")
        child = Task(task_type="child")
        tree.add_task(root)
        tree.add_task(child, parent_id=root.task_id)
        assert tree.get_depth(root.task_id) == 1
        assert tree.get_depth(child.task_id) == 2

    def test_to_dict(self):
        tree = TaskTree()
        task = Task(task_type="t")
        tree.add_task(task)
        d = tree.to_dict()
        assert task.task_id in d
        assert d[task.task_id]["task_type"] == "t"


# ======================================================================
# 7.5 — Event System & Error Handling
# ======================================================================


class TestSystemEvent:
    def test_default_fields(self):
        event = SystemEvent(event_type=EventType.ROUTE_RESOLVED, source="test")
        assert event.event_type == EventType.ROUTE_RESOLVED
        assert event.event_id != ""
        assert event.timestamp > 0

    def test_custom_event_id(self):
        event = SystemEvent(event_type=EventType.TASK_DISPATCHED, source="s", event_id="e1")
        assert event.event_id == "e1"

    def test_to_dict(self):
        event = SystemEvent(
            event_type=EventType.ERROR_OCCURRED,
            source="handler",
            payload={"msg": "boom"},
        )
        d = event.to_dict()
        assert d["event_type"] == "error.occurred"
        assert d["source"] == "handler"
        assert d["payload"] == {"msg": "boom"}


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []

        async def handler(event: SystemEvent):
            received.append(event)

        bus.subscribe(EventType.ROUTE_RESOLVED, handler)

        event = SystemEvent(event_type=EventType.ROUTE_RESOLVED, source="test")
        asyncio.run(bus.emit(event))
        assert len(received) == 1

    def test_wildcard_handler(self):
        bus = EventBus()
        received = []

        async def handler(event: SystemEvent):
            received.append(event)

        bus.subscribe(None, handler)
        asyncio.run(bus.emit(SystemEvent(event_type=EventType.ROUTE_RESOLVED, source="s")))
        asyncio.run(bus.emit(SystemEvent(event_type=EventType.TASK_COMPLETED, source="s")))
        assert len(received) == 2

    def test_unsubscribe(self):
        bus = EventBus()

        async def handler(event: SystemEvent):
            pass

        bus.subscribe(EventType.ROUTE_RESOLVED, handler)
        assert bus.unsubscribe(EventType.ROUTE_RESOLVED, handler) is True

        event = SystemEvent(event_type=EventType.ROUTE_RESOLVED, source="s")
        asyncio.run(bus.emit(event))

    def test_unsubscribe_nonexistent(self):
        bus = EventBus()
        async def h(event): pass
        assert bus.unsubscribe(EventType.ROUTE_RESOLVED, h) is False

    def test_unsubscribe_wildcard(self):
        bus = EventBus()

        async def h(event):
            pass

        bus.subscribe(None, h)
        assert bus.unsubscribe(None, h) is True
        assert bus.unsubscribe(None, h) is False

    def test_get_history(self):
        bus = EventBus()
        asyncio.run(bus.emit(SystemEvent(event_type=EventType.TASK_COMPLETED, source="s")))
        history = bus.get_history()
        assert len(history) == 1

    def test_get_history_filtered(self):
        bus = EventBus()
        asyncio.run(bus.emit(SystemEvent(event_type=EventType.TASK_COMPLETED, source="s")))
        asyncio.run(bus.emit(SystemEvent(event_type=EventType.ROUTE_RESOLVED, source="s")))
        filtered = bus.get_history(event_type=EventType.TASK_COMPLETED)
        assert len(filtered) == 1
        assert filtered[0].event_type == EventType.TASK_COMPLETED

    def test_clear_history(self):
        bus = EventBus()
        bus = EventBus()
        asyncio.run(bus.emit(SystemEvent(event_type=EventType.TASK_COMPLETED, source="s")))
        bus.clear_history()
        assert bus.get_history() == []

    def test_handler_exception_does_not_crash_bus(self):
        bus = EventBus()

        async def failing_handler(event: SystemEvent):
            raise RuntimeError("handler failed")

        async def good_handler(event: SystemEvent):
            pass

        bus.subscribe(EventType.ROUTE_RESOLVED, failing_handler)
        bus.subscribe(EventType.ROUTE_RESOLVED, good_handler)

        # Should not raise
        asyncio.run(bus.emit(SystemEvent(event_type=EventType.ROUTE_RESOLVED, source="s")))


class TestEventType:
    def test_values(self):
        assert EventType.ROUTE_RESOLVED.value == "route.resolved"
        assert EventType.CIRCUIT_OPEN.value == "circuit.open"
        assert EventType.WORKFLOW_STARTED.value == "workflow.started"


class TestErrorClassifier:
    def test_classify_timeout(self):
        classifier = ErrorClassifier()
        exc = TimeoutError("timed out")
        cat, sev = classifier.classify(exc)
        assert cat == ErrorCategory.TEMPORARY
        assert sev == ErrorSeverity.LOW

    def test_classify_permanent(self):
        classifier = ErrorClassifier()
        exc = ValueError("invalid")
        cat, sev = classifier.classify(exc)
        assert cat == ErrorCategory.PERMANENT

    def test_classify_unknown(self):
        classifier = ErrorClassifier()
        exc = StopIteration()
        cat, sev = classifier.classify(exc)
        assert cat == ErrorCategory.UNKNOWN

    def test_register_custom(self):
        classifier = ErrorClassifier()
        classifier.register(LookupError, ErrorCategory.TEMPORARY, ErrorSeverity.HIGH)
        # KeyError is a subclass of LookupError, so it matches the custom rule
        cat, sev = classifier.classify(LookupError("missing"))
        assert cat == ErrorCategory.TEMPORARY

    def test_classify_memory_error(self):
        classifier = ErrorClassifier()
        cat, sev = classifier.classify(MemoryError("oom"))
        assert cat == ErrorCategory.SYSTEM
        assert sev == ErrorSeverity.CRITICAL


class TestCentralizedErrorHandler:
    @pytest.mark.asyncio
    async def test_handle_exception(self):
        handler = CentralizedErrorHandler()
        response = await handler.handle(ValueError("bad value"))
        assert isinstance(response, ErrorResponse)
        assert "bad value" in response.message
        assert response.category == ErrorCategory.PERMANENT

    @pytest.mark.asyncio
    async def test_error_id_is_uuid(self):
        handler = CentralizedErrorHandler()
        response = await handler.handle(RuntimeError("err"))
        assert len(response.error_id) > 0

    @pytest.mark.asyncio
    async def test_handler_callback(self):
        handler = CentralizedErrorHandler()
        responses = []

        async def callback(response: ErrorResponse):
            responses.append(response)

        handler.add_handler(callback)
        await handler.handle(ValueError("test"))
        assert len(responses) == 1
        assert responses[0].category == ErrorCategory.PERMANENT

    @pytest.mark.asyncio
    async def test_remove_handler(self):
        handler = CentralizedErrorHandler()
        async def cb(r): pass
        handler.add_handler(cb)
        assert handler.remove_handler(cb) is True
        assert handler.remove_handler(cb) is False

    @pytest.mark.asyncio
    async def test_emit_event_to_bus(self):
        bus = EventBus()
        error_handler = CentralizedErrorHandler(event_bus=bus)
        events = []

        async def record(event):
            events.append(event)

        bus.subscribe(EventType.ERROR_OCCURRED, record)
        await error_handler.handle(ValueError("test"), context={"module": "routing"})
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_wrap_decorator_success(self):
        handler = CentralizedErrorHandler()

        @handler.wrap
        async def good_func():
            return 42

        result = await good_func()
        assert result == 42

    @pytest.mark.asyncio
    async def test_wrap_decorator_failure(self):
        handler = CentralizedErrorHandler()

        @handler.wrap
        async def bad_func():
            raise ValueError("wrapped")

        result = await bad_func()
        assert isinstance(result, ErrorResponse)
        assert result.category == ErrorCategory.PERMANENT


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_open_on_failure_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_allow_request_when_closed(self):
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_deny_request_when_open(self):
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=60.0,
        )
        cb.record_failure()
        assert cb.allow_request() is False

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.01,
        )
        cb.record_failure()
        time.sleep(0.02)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_close_after_successes(self):
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.01,
            consecutive_successes_to_close=2,
        )
        cb.record_failure()
        time.sleep(0.02)
        cb.allow_request()  # transitions to HALF_OPEN

        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_open_again_from_half_open(self):
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.01,
        )
        cb.record_failure()  # → OPEN
        time.sleep(0.02)
        cb.allow_request()  # → HALF_OPEN
        cb.record_failure()  # → OPEN
        assert cb.state == CircuitState.OPEN

    def test_reset(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_get_metrics(self):
        cb = CircuitBreaker(name="test-metrics", failure_threshold=5)
        metrics = cb.get_metrics()
        assert metrics["name"] == "test-metrics"
        assert metrics["state"] == "closed"
        assert metrics["failure_threshold"] == 5

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # not enough consecutive failures


class TestRetryHandler:
    @pytest.mark.asyncio
    async def test_retry_on_temporary_failure(self):
        retry = RetryHandler(max_retries=2, base_delay=0.01)
        attempt_count = [0]

        async def flaky_func():
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                raise TimeoutError("timeout")
            return "success"

        result = await retry.execute(flaky_func)
        assert result == "success"
        assert attempt_count[0] == 3

    @pytest.mark.asyncio
    async def test_exhaust_retries(self):
        retry = RetryHandler(max_retries=2, base_delay=0.01)
        attempt_count = [0]

        async def always_fails():
            attempt_count[0] += 1
            raise TimeoutError("always fails")

        with pytest.raises(TimeoutError):
            await retry.execute(always_fails)
        assert attempt_count[0] == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        retry = RetryHandler(max_retries=3, base_delay=0.01)
        attempt_count = [0]

        async def raises_value_error():
            attempt_count[0] += 1
            raise ValueError("non-retryable")

        with pytest.raises(ValueError):
            await retry.execute(raises_value_error, retryable_exceptions=(TimeoutError, ConnectionError))
        assert attempt_count[0] == 1

    @pytest.mark.asyncio
    async def test_custom_retryable_exceptions(self):
        retry = RetryHandler(max_retries=1, base_delay=0.01)

        async def flaky():
            raise ValueError("custom retryable")

        with pytest.raises(ValueError):
            await retry.execute(flaky, retryable_exceptions=(TimeoutError,))


class TestMessageQueueEventProducer:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        bus = EventBus()
        producer = MessageQueueEventProducer(bus)
        await producer.start()
        assert producer._running is True
        await producer.stop()
        assert producer._running is False

    @pytest.mark.asyncio
    async def test_produce_events(self):
        bus = EventBus()
        producer = MessageQueueEventProducer(bus, topic_prefix="vertex")
        await producer.start()

        # Manually trigger the event handler
        event = SystemEvent(event_type=EventType.ROUTE_RESOLVED, source="test")
        await producer._on_event(event)

        produced = producer.get_produced_events()
        assert len(produced) == 1
        assert produced[0].event_type == EventType.ROUTE_RESOLVED

    @pytest.mark.asyncio
    async def test_does_not_produce_when_stopped(self):
        bus = EventBus()
        producer = MessageQueueEventProducer(bus)
        event = SystemEvent(event_type=EventType.ROUTE_RESOLVED, source="test")
        await producer._on_event(event)
        assert producer.get_produced_events() == []


# ======================================================================
# Package __init__ exports
# ======================================================================


class TestPackageExports:
    """Verify all expected symbols are re-exported from src.routing."""

    def test_conditional_exports(self):
        import src.routing

        for name in ["ConditionalRouter", "DynamicRouter", "MapReduceRouter", "PathMap", "RouteCondition", "BranchSpec"]:
            assert hasattr(src.routing, name), f"Missing export: {name}"

    def test_loops_exports(self):
        import src.routing

        for name in ["ForLoop", "WhileLoop", "LoopController", "LoopDetector", "RecursionLimit", "MapLoop", "NestedLoop", "LoopAction"]:
            assert hasattr(src.routing, name), f"Missing export: {name}"

    def test_hitl_exports(self):
        import src.routing

        for name in ["InterruptSignal", "ResumeSignal", "ApprovalFlow", "HumanInTheLoopMiddleware", "InputCollector", "InterruptReason"]:
            assert hasattr(src.routing, name), f"Missing export: {name}"

    def test_workflow_exports(self):
        import src.routing

        for name in ["Task", "TaskResult", "TaskStatus", "TaskTree", "HandlerRegistry", "TaskDispatcher", "Workflow", "WorkflowStep", "WorkflowStepStatus", "WorkflowResult"]:
            assert hasattr(src.routing, name), f"Missing export: {name}"

    def test_events_exports(self):
        import src.routing

        for name in ["SystemEvent", "EventBus", "EventType", "CircuitBreaker", "CircuitState", "CentralizedErrorHandler", "ErrorClassifier", "ErrorCategory", "ErrorSeverity", "ErrorResponse", "RetryHandler", "MessageQueueEventProducer"]:
            assert hasattr(src.routing, name), f"Missing export: {name}"

    def test_model_router_exports(self):
        import src.routing

        for name in ["ModelConfig", "ModelRouter", "RoutingResult", "TaskType"]:
            assert hasattr(src.routing, name), f"Missing export: {name}"


# ------------------------------------------------------------------
# Model Router tests (Task 10.5)
# ------------------------------------------------------------------

class TestModelConfig:
    def test_defaults(self) -> None:
        from src.routing.models import ModelConfig

        mc = ModelConfig(name="test-model")
        assert mc.name == "test-model"
        assert mc.provider == ""
        assert mc.task_types == []
        assert mc.cost_per_1k_input == 0.0
        assert mc.context_window == 8192
        assert mc.priority == 0

    def test_full_config(self) -> None:
        from src.routing.models import ModelConfig, TaskType

        mc = ModelConfig(
            name="claude-sonnet-4",
            provider="anthropic",
            task_types=[TaskType.CHAT, TaskType.CODE],
            cost_per_1k_input=3.0,
            cost_per_1k_output=15.0,
            context_window=200000,
            priority=10,
        )
        assert mc.provider == "anthropic"
        assert TaskType.CHAT in mc.task_types
        assert mc.cost_per_1k_input == 3.0
        assert mc.context_window == 200000


class TestTaskType:
    def test_all_types(self) -> None:
        from src.routing.models import TaskType

        assert TaskType.CHAT.value == "chat"
        assert TaskType.CODE.value == "code"
        assert TaskType.REASONING.value == "reasoning"
        assert TaskType.CREATIVE.value == "creative"
        assert TaskType.RESEARCH.value == "research"
        assert TaskType.EMBEDDING.value == "embedding"

    def test_str_usage(self) -> None:
        from src.routing.models import TaskType

        assert str(TaskType.CHAT) == "TaskType.CHAT"


class TestModelRouter:
    def test_route_simple(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="gpt-4o", task_types=[TaskType.CHAT], priority=10),
            ModelConfig(name="gpt-3.5", task_types=[TaskType.CHAT], priority=0),
        ])
        result = router.route(TaskType.CHAT)
        assert result.chosen_model == "gpt-4o"
        assert not result.fallback_used

    def test_route_fallback(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="gpt-4o", task_types=[TaskType.CHAT], priority=10),
            ModelConfig(name="claude-sonnet", task_types=[TaskType.CHAT], priority=5),
            ModelConfig(name="gpt-3.5", task_types=[TaskType.CHAT], priority=0),
        ])
        # Ask for a model that doesn't exist for CODE type
        result = router.route(TaskType.CODE)
        # None of the models have CODE in task_types
        assert result.fallback_used
        # The router should fall back to default or any model
        assert result.chosen_model

    def test_route_with_preferred(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="gpt-4o", task_types=[TaskType.CHAT], priority=10),
            ModelConfig(name="gpt-3.5", task_types=[TaskType.CHAT], priority=0),
        ])
        result = router.route(TaskType.CHAT, constraints={"preferred_model": "gpt-3.5"})
        assert result.chosen_model == "gpt-3.5"

    def test_route_with_cost_constraint(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="gpt-4o", task_types=[TaskType.CHAT], cost_per_1k_input=10.0, priority=10),
            ModelConfig(name="gpt-3.5", task_types=[TaskType.CHAT], cost_per_1k_input=1.0, priority=5),
            ModelConfig(name="claude-haiku", task_types=[TaskType.CHAT], cost_per_1k_input=0.5, priority=0),
        ])
        # Max cost 2.0 should exclude gpt-4o (10.0), pick gpt-3.5
        result = router.route(TaskType.CHAT, constraints={"max_cost": 2.0})
        assert result.chosen_model == "gpt-3.5"

    def test_route_with_context_constraint(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="gpt-3.5", task_types=[TaskType.CHAT], context_window=4096, priority=10),
            ModelConfig(name="claude-sonnet", task_types=[TaskType.CHAT], context_window=200000, priority=5),
        ])
        result = router.route(TaskType.CHAT, constraints={"min_context": 10000})
        assert result.chosen_model == "claude-sonnet"

    def test_route_no_models(self) -> None:
        from src.routing.models import ModelRouter, TaskType

        router = ModelRouter()
        with pytest.raises(RuntimeError, match="No model available"):
            router.route(TaskType.CHAT)

    def test_add_and_remove_model(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter()
        mc = ModelConfig(name="test-model", task_types=[TaskType.CHAT])
        router.add_model(mc)
        assert router.get_model("test-model") is mc

        router.remove_model("test-model")
        assert router.get_model("test-model") is None

    def test_list_models(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="m1", task_types=[TaskType.CHAT]),
            ModelConfig(name="m2", task_types=[TaskType.CODE]),
        ])
        all_models = router.list_models()
        assert len(all_models) == 2
        chat_models = router.list_models(TaskType.CHAT)
        assert len(chat_models) == 1

    def test_cheapest_model_for(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="expensive", task_types=[TaskType.CHAT], cost_per_1k_input=10.0),
            ModelConfig(name="cheap", task_types=[TaskType.CHAT], cost_per_1k_input=0.5),
        ])
        cheapest = router.cheapest_model_for(TaskType.CHAT)
        assert cheapest == "cheap"

    def test_cheapest_model_for_no_match(self) -> None:
        from src.routing.models import ModelRouter, TaskType

        router = ModelRouter()
        assert router.cheapest_model_for(TaskType.CHAT) is None

    def test_estimate_cost(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="m1", task_types=[TaskType.CHAT], cost_per_1k_input=5.0, cost_per_1k_output=15.0),
        ])
        cost = router.estimate_cost("m1", input_tokens=1000, output_tokens=500)
        # 1000/1000 * 5 + 500/1000 * 15 = 5 + 7.5 = 12.5
        assert cost == 12.5

    def test_estimate_cost_unknown_model(self) -> None:
        from src.routing.models import ModelRouter

        router = ModelRouter()
        assert router.estimate_cost("nonexistent") == 0.0

    def test_invoke_with_fallback(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="failing", task_types=[TaskType.CHAT], priority=10),
            ModelConfig(name="working", task_types=[TaskType.CHAT], priority=5),
        ])
        call_count = {"failing": 0, "working": 0}

        def invoke(model_name: str, **kwargs: Any) -> str:
            if model_name == "failing":
                call_count["failing"] += 1
                raise RuntimeError("Model failed")
            call_count["working"] += 1
            return f"Result from {model_name}"

        result = router.invoke_with_fallback(TaskType.CHAT, invoke)
        assert result == "Result from working"
        assert call_count["failing"] == 1

    def test_invoke_with_fallback_all_fail(self) -> None:
        from src.routing.models import ModelConfig, ModelRouter, TaskType

        router = ModelRouter(models=[
            ModelConfig(name="m1", task_types=[TaskType.CHAT], priority=10),
            ModelConfig(name="m2", task_types=[TaskType.CHAT], priority=5),
        ])

        def invoke(model_name: str, **kwargs: Any) -> str:
            raise RuntimeError(f"{model_name} failed")

        with pytest.raises(RuntimeError, match="All models failed"):
            router.invoke_with_fallback(TaskType.CHAT, invoke, max_retries=2)

    def test_routing_result_dataclass(self) -> None:
        from src.routing.models import RoutingResult, TaskType

        result = RoutingResult(
            chosen_model="gpt-4o",
            task_type=TaskType.CODE,
            fallback_used=True,
            fallback_chain=["gpt-3.5"],
            estimated_cost=5.0,
            reason="Fallback after failure",
        )
        assert result.chosen_model == "gpt-4o"
        assert result.task_type == TaskType.CODE
        assert result.fallback_used
        assert "gpt-3.5" in result.fallback_chain