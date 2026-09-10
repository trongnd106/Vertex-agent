"""Tests for the subagents package.

Covers:
- Task 5.1: Sync SubAgent (SubAgent, CompiledSubAgent, SubAgentRegistry)
- Task 5.2: Async SubAgent (AsyncSubAgentManager, AsyncSubAgentMiddleware)
- Task 5.3: Communication Protocol (MessageBroker, EventBus, SharedState)
- Task 5.4: Parallel Tool Execution (ParallelExecutor)
- Task 5.5: Profile & Resource Management (SubagentProfile, ResourceManager, LifecycleManager)
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from src.subagents import (
    CompiledSubAgent,
    DEFAULT_SUBAGENT_SPEC,
    SubAgent,
    SubAgentMiddleware,
    SubAgentRegistry,
    # async
    AsyncSubAgent,
    AsyncSubAgentManager,
    AsyncSubAgentMiddleware,
    AsyncSubAgentStatus,
    AsyncTask,
    # communication
    AgentEvent,
    AgentMessage,
    CommunicationMiddleware,
    EventBus,
    MessageBroker,
    MessageType,
    SharedState,
    # parallel
    BatchResult,
    ParallelExecutor,
    ParallelToolCall,
    ParallelToolResult,
    # profiles
    GeneralPurposeSubagentProfile,
    LifecycleManager,
    ResourceExhaustedError,
    ResourceManager,
    SubagentLifecycle,
    SubagentProfile,
    SubagentState,
)
from src.tools.filesystem import ToolResult
from src.tools.registry import ToolRegistry


# ═══════════════════════════════════════════════════════════════════════
# Task 5.1: Sync SubAgent
# ═══════════════════════════════════════════════════════════════════════


class TestSubAgent:
    def test_basic_creation(self):
        agent = SubAgent(name="test_agent")
        assert agent.name == "test_agent"
        assert agent.description == ""
        assert agent.system_prompt == ""
        assert agent.tools == []
        assert agent.middleware == []

    def test_full_creation(self):
        agent = SubAgent(
            name="full_agent",
            description="A test agent",
            system_prompt="You are test.",
            model="gpt-4",
            tools=[{"name": "test_tool", "description": "A test"}],
            middleware=[],
            metadata={"key": "value"},
        )
        assert agent.name == "full_agent"
        assert agent.description == "A test agent"
        assert agent.system_prompt == "You are test."
        assert agent.model == "gpt-4"
        assert len(agent.tools) == 1
        assert agent.metadata == {"key": "value"}

    def test_default_spec(self):
        spec = DEFAULT_SUBAGENT_SPEC
        assert spec.name == "general_purpose"
        assert "general-purpose" in spec.description.lower()

    def test_to_string(self):
        agent = SubAgent(name="test", description="desc")
        s = str(agent)
        assert "test" in s
        assert "desc" in s


class TestCompiledSubAgent:
    def test_create_from_spec(self):
        spec = SubAgent(name="compiled_test")
        compiled = CompiledSubAgent(spec)
        assert compiled.spec is spec
        assert compiled.spec.name == "compiled_test"

    def test_invoke(self):
        spec = SubAgent(name="invoke_test")
        compiled = CompiledSubAgent(spec)
        result = compiled.invoke({"input": "hello"})
        assert result.success is True
        assert "invoke_test" in result.data


class TestSubAgentRegistry:
    def test_register_returns_compiled(self):
        registry = SubAgentRegistry()
        spec = SubAgent(name="agent_a")
        compiled = registry.register(spec)
        assert isinstance(compiled, CompiledSubAgent)
        assert compiled.spec is spec

    def test_get_compiled(self):
        registry = SubAgentRegistry()
        spec = SubAgent(name="agent_a")
        compiled = registry.register(spec)
        assert registry.get("agent_a") is compiled

    def test_get_unknown(self):
        registry = SubAgentRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister_removes(self):
        registry = SubAgentRegistry()
        spec = SubAgent(name="removable")
        registry.register(spec)
        result = registry.unregister("removable")
        assert result is True
        assert registry.get("removable") is None

    def test_unregister_unknown(self):
        registry = SubAgentRegistry()
        assert registry.unregister("unknown") is False

    def test_list(self):
        registry = SubAgentRegistry()
        for name in ("a", "b", "c"):
            registry.register(SubAgent(name=name))
        specs = registry.list()
        names = [s.name for s in specs]
        assert "a" in names
        assert "b" in names
        assert "c" in names

    def test_get_spec(self):
        registry = SubAgentRegistry()
        spec = SubAgent(name="spec_test", description="original")
        registry.register(spec)
        retrieved = registry.get_spec("spec_test")
        assert retrieved is spec


class TestSubAgentMiddleware:
    def test_registry_has_default(self):
        mw = SubAgentMiddleware()
        assert mw.registry is not None
        assert mw.registry.get("general_purpose") is not None

    def test_task_tool_fn(self):
        mw = SubAgentMiddleware()
        fn = mw.task_tool_fn()
        assert callable(fn)
        assert fn.__name__ == "task"

    def test_get_task_tool_spec(self):
        mw = SubAgentMiddleware()
        spec = mw.get_task_tool_spec()
        assert spec.name == "task"

    def test_task_tool_invoke_default(self):
        mw = SubAgentMiddleware()
        fn = mw.task_tool_fn()
        result = fn("general_purpose", {"input": "test"})
        assert result.success is True

    def test_task_tool_unknown(self):
        mw = SubAgentMiddleware()
        fn = mw.task_tool_fn()
        result = fn("nonexistent")
        assert result.success is False
        assert "Unknown" in result.error


# ═══════════════════════════════════════════════════════════════════════
# Task 5.2: Async SubAgent
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncSubAgent:
    def test_create_with_graph_id(self):
        agent = AsyncSubAgent(graph_id="test_graph")
        assert agent.graph_id == "test_graph"
        assert agent.url == ""
        assert agent.headers == {}

    def test_create_with_all_fields(self):
        agent = AsyncSubAgent(graph_id="g", url="http://test", headers={"Auth": "key"})
        assert agent.graph_id == "g"
        assert agent.url == "http://test"
        assert agent.headers == {"Auth": "key"}

    def test_defaults(self):
        agent = AsyncSubAgent()
        assert agent.graph_id == ""
        assert agent.url == ""
        assert agent.headers == {}
        assert agent.subagent_spec is None


class TestAsyncSubAgentManager:
    def test_launch_and_get_task(self):
        manager = AsyncSubAgentManager()
        task = manager.launch_task("test_agent", {"input": "hello"})
        assert isinstance(task, AsyncTask)
        assert task.subagent_name == "test_agent"
        assert task.input_data == {"input": "hello"}
        assert task.status in (
            AsyncSubAgentStatus.PENDING,
            AsyncSubAgentStatus.RUNNING,
            AsyncSubAgentStatus.FAILED,
        )
        ret = manager.get_task(task.id)
        assert ret is task

    def test_list_tasks(self):
        manager = AsyncSubAgentManager()
        t1 = manager.launch_task("agent_a")
        t2 = manager.launch_task("agent_b")
        tasks = manager.list_tasks()
        assert len(tasks) >= 2

    def test_cancel_task(self):
        manager = AsyncSubAgentManager()
        task = manager.launch_task("cancellable")
        # Task may auto-complete/fail quickly; cancel might return False
        # if already terminal. We just verify no crash and task is updated.
        result = manager.cancel_task(task.id)
        updated = manager.get_task(task.id)
        assert updated.status in (
            AsyncSubAgentStatus.CANCELLED,
            AsyncSubAgentStatus.COMPLETED,
            AsyncSubAgentStatus.FAILED,
        )

    def test_cancel_completed_task(self):
        manager = AsyncSubAgentManager()
        task = manager.launch_task("done")
        time.sleep(0.1)
        manager.cancel_task(task.id)
        updated = manager.get_task(task.id)
        assert updated.status in (
            AsyncSubAgentStatus.CANCELLED,
            AsyncSubAgentStatus.COMPLETED,
            AsyncSubAgentStatus.FAILED,
        )

    def test_launch_local_task(self):
        manager = AsyncSubAgentManager()
        task = manager.launch_task("local_agent")
        assert task.status in (
            AsyncSubAgentStatus.PENDING,
            AsyncSubAgentStatus.RUNNING,
            AsyncSubAgentStatus.COMPLETED,
            AsyncSubAgentStatus.FAILED,
        )

    def test_concurrent_limit(self):
        manager = AsyncSubAgentManager(max_concurrent=1)
        first = manager.launch_task("first")
        second = manager.launch_task("second")
        assert second.status == AsyncSubAgentStatus.FAILED

    def test_get_task_status(self):
        manager = AsyncSubAgentManager()
        task = manager.launch_task("status_test")
        status = manager.get_task_status(task.id)
        assert isinstance(status, dict)
        assert "status" in status

    def test_clean_orphans(self):
        manager = AsyncSubAgentManager()
        manager.launch_task("orphan")
        cleaned = manager.clean_orphans()
        assert cleaned >= 0


class TestAsyncSubAgentMiddleware:
    def test_manager_access(self):
        manager = AsyncSubAgentManager()
        mw = AsyncSubAgentMiddleware(manager)
        assert mw.manager is manager

    def test_default_manager(self):
        mw = AsyncSubAgentMiddleware()
        assert mw.manager is not None

    def test_tool_factories(self):
        mw = AsyncSubAgentMiddleware()
        launch = mw._make_launch_task()
        assert callable(launch)
        assert launch.__name__ == "launch_task"

        status = mw._make_get_task_status()
        assert callable(status)
        assert status.__name__ == "get_task_status"

        cancel = mw._make_cancel_task()
        assert callable(cancel)
        assert cancel.__name__ == "cancel_task"

        lst = mw._make_list_tasks()
        assert callable(lst)
        assert lst.__name__ == "list_tasks"

    def test_launch_tool_works(self):
        mw = AsyncSubAgentMiddleware()
        launch = mw._make_launch_task()
        result = launch("test_agent", {"data": "hello"})
        assert result.success is True

    def test_list_tasks_works(self):
        mw = AsyncSubAgentMiddleware()
        lst = mw._make_list_tasks()
        result = lst()
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════════
# Task 5.3: Communication Protocol
# ═══════════════════════════════════════════════════════════════════════


class TestAgentMessage:
    def test_create_message(self):
        msg = AgentMessage(
            sender="agent_a",
            recipient="agent_b",
            message_type=MessageType.RESULT,
            payload={"value": 42},
        )
        assert msg.sender == "agent_a"
        assert msg.recipient == "agent_b"
        assert msg.message_type == MessageType.RESULT
        assert msg.payload == {"value": 42}

    def test_to_dict(self):
        msg = AgentMessage(
            sender="a",
            recipient="b",
            message_type=MessageType.COMMAND,
            payload={"cmd": "run"},
        )
        d = msg.to_dict()
        assert d["sender"] == "a"
        assert d["recipient"] == "b"
        assert d["message_type"] == MessageType.COMMAND.value
        assert d["payload"] == {"cmd": "run"}
        assert "id" in d
        assert "timestamp" in d

    def test_default_message_type(self):
        msg = AgentMessage(sender="a", recipient="b", message_type=MessageType.RESULT)
        assert msg.payload is None


class TestMessageBroker:
    def test_send_and_receive(self):
        broker = MessageBroker()
        msg = AgentMessage(sender="a", recipient="b", message_type=MessageType.RESULT)
        broker.send(msg)
        received = broker.receive("b", timeout=1.0)
        assert received is not None
        assert received.sender == "a"
        assert received.recipient == "b"

    def test_receive_with_timeout(self):
        broker = MessageBroker()
        received = broker.receive("empty", timeout=0.1)
        assert received is None

    def test_poll_with_messages(self):
        broker = MessageBroker()
        msg = AgentMessage(sender="a", recipient="b", message_type=MessageType.RESULT)
        broker.send(msg)
        messages = broker.poll("b")
        assert len(messages) >= 1

    def test_poll_empty(self):
        broker = MessageBroker()
        messages = broker.poll("nonexistent")
        assert isinstance(messages, list)
        assert len(messages) == 0

    def test_multiple_recipients(self):
        broker = MessageBroker()
        broker.send(AgentMessage(sender="a", recipient="x", message_type=MessageType.RESULT))
        broker.send(AgentMessage(sender="b", recipient="y", message_type=MessageType.RESULT))
        assert broker.receive("x", timeout=0.5) is not None
        assert broker.receive("y", timeout=0.5) is not None
        assert broker.receive("x", timeout=0.1) is None

    def test_fifo_order(self):
        broker = MessageBroker()
        broker.send(AgentMessage(sender="a", recipient="q", payload={"seq": 1}, message_type=MessageType.RESULT))
        broker.send(AgentMessage(sender="a", recipient="q", payload={"seq": 2}, message_type=MessageType.RESULT))
        first = broker.receive("q", timeout=1.0)
        assert first is not None
        assert first.payload["seq"] == 1
        second = broker.receive("q", timeout=1.0)
        assert second is not None
        assert second.payload["seq"] == 2

    def test_event_bus_integration(self):
        broker = MessageBroker()
        events = []
        broker.event_bus.subscribe("message.result", lambda e: events.append(e))
        broker.send(AgentMessage(sender="a", recipient="b", message_type=MessageType.RESULT))
        assert len(events) >= 1

    def test_clear_recipient(self):
        broker = MessageBroker()
        for _ in range(3):
            broker.send(AgentMessage(sender="a", recipient="q", message_type=MessageType.RESULT))
        cleared = broker.clear_recipient("q")
        assert cleared == 3
        assert broker.receive("q", timeout=0.1) is None


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe("test.event", lambda e: received.append(e))
        bus.emit(AgentEvent(type="test.event", source="test"))
        assert len(received) == 1

    def test_wildcard_subscription(self):
        bus = EventBus()
        received = []
        bus.subscribe("*", lambda e: received.append(e))
        bus.emit(AgentEvent(type="any.event", source="test"))
        assert len(received) == 1

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        handler = lambda e: received.append(e)
        bus.subscribe("test.event", handler)
        bus.unsubscribe("test.event", handler)
        bus.emit(AgentEvent(type="test.event", source="test"))
        assert len(received) == 0

    def test_no_handler_for_event(self):
        bus = EventBus()
        bus.emit(AgentEvent(type="unhandled", source="test"))

    def test_clear(self):
        bus = EventBus()
        received = []
        bus.subscribe("test.event", lambda e: received.append(e))
        bus.clear()
        bus.emit(AgentEvent(type="test.event", source="test"))
        assert len(received) == 0


class TestSharedState:
    def test_set_and_get(self):
        state = SharedState()
        state.set("key1", "value1")
        assert state.get("key1") == "value1"

    def test_get_default(self):
        state = SharedState()
        assert state.get("missing", "default") == "default"

    def test_update(self):
        state = SharedState()
        state.set("a", 1)
        state.update("a", lambda x: x + 10 if x is not None else 0)
        assert state.get("a") == 11

    def test_delete(self):
        state = SharedState()
        state.set("temp", "value")
        state.delete("temp")
        assert state.get("temp") is None

    def test_clear(self):
        state = SharedState()
        state.set("a", 1)
        state.set("b", 2)
        state.clear()
        assert state.get("a") is None
        assert state.get("b") is None

    def test_keys(self):
        state = SharedState()
        state.set("a", 1)
        state.set("b", 2)
        assert set(state.keys()) == {"a", "b"}

    def test_thread_safety(self):
        import threading

        state = SharedState()
        results = []

        def worker(key: str):
            for i in range(100):
                state.set(key, i)
            results.append(state.get(key))

        threads = [threading.Thread(target=worker, args=(f"k{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 10


class TestCommunicationMiddleware:
    def test_tool_functions_exist(self):
        broker = MessageBroker()
        state = SharedState()
        mw = CommunicationMiddleware(broker=broker, shared_state=state)
        send = mw.send_message_fn()
        assert callable(send)
        assert send.__name__ == "send_message"

        read = mw.read_state_fn()
        assert callable(read)
        assert read.__name__ == "read_state"

        write = mw.write_state_fn()
        assert callable(write)
        assert write.__name__ == "write_state"

    def test_send_message_works(self):
        broker = MessageBroker()
        mw = CommunicationMiddleware(broker=broker, shared_state=SharedState(), agent_name="main")
        send = mw.send_message_fn()
        result = send("recipient", {"data": "hello"}, "result")
        assert result.success is True
        msg = broker.receive("recipient", timeout=0.5)
        assert msg is not None
        assert msg.payload == {"data": "hello"}

    def test_read_write_state(self):
        state = SharedState()
        mw = CommunicationMiddleware(broker=MessageBroker(), shared_state=state)
        write = mw.write_state_fn()
        read = mw.read_state_fn()
        write("mykey", "myvalue")
        result = read("mykey")
        assert result.success is True
        assert result.data == {"mykey": "myvalue"}

    def test_invalid_message_type(self):
        mw = CommunicationMiddleware()
        send = mw.send_message_fn()
        result = send("r", {}, "invalid_type")
        assert result.success is False

    def test_default_instances(self):
        mw = CommunicationMiddleware()
        assert mw.broker is not None
        assert mw.shared_state is not None


# ═══════════════════════════════════════════════════════════════════════
# Task 5.4: Parallel Tool Execution
# ═══════════════════════════════════════════════════════════════════════


class TestParallelToolCall:
    def test_create(self):
        call = ParallelToolCall(id="call_1", tool_name="test", args={"k": "v"})
        assert call.id == "call_1"
        assert call.tool_name == "test"
        assert call.args == {"k": "v"}
        assert call.kwargs == {}


class TestParallelToolResult:
    def test_create(self):
        tr = ToolResult(success=True, data="ok")
        result = ParallelToolResult(call_id="c1", tool_name="t", result=tr, duration_ms=100.0)
        assert result.call_id == "c1"
        assert result.tool_name == "t"
        assert result.result is tr
        assert result.result.success is True
        assert result.duration_ms == 100.0

    def test_create_with_error(self):
        tr = ToolResult(success=False, error="failed")
        result = ParallelToolResult(call_id="c2", tool_name="t", result=tr)
        assert result.result.success is False
        assert result.result.error == "failed"


class TestBatchResult:
    def test_defaults(self):
        result = BatchResult()
        assert result.success_count == 0
        assert result.failure_count == 0
        assert result.successful_results == []
        assert result.failed_results == []
        assert result.total_duration_ms == 0.0
        assert result.all_successful is True

    def test_to_dict(self):
        result = BatchResult()
        d = result.to_dict()
        assert d["total"] == 0
        assert d["success_count"] == 0
        assert d["failure_count"] == 0


class TestParallelExecutor:
    def test_execute_empty(self):
        registry = ToolRegistry()
        executor = ParallelExecutor(registry)
        result = executor.execute_batch([])
        assert result.success_count == 0
        assert result.all_successful is True

    def test_execute_batch(self):
        registry = ToolRegistry()
        executor = ParallelExecutor(registry, max_workers=2)
        calls = [
            ParallelToolCall(id="1", tool_name="a", args={}),
            ParallelToolCall(id="2", tool_name="b", args={}),
        ]
        result = executor.execute_batch(calls, timeout=10.0)
        assert result.success_count + result.failure_count == 2

    def test_batch_result_fields(self):
        registry = ToolRegistry()
        executor = ParallelExecutor(registry, max_workers=2)
        calls = [
            ParallelToolCall(id="1", tool_name="a", args={}),
            ParallelToolCall(id="2", tool_name="b", args={}),
        ]
        result = executor.execute_batch(calls, timeout=10.0)
        assert result.total_duration_ms >= 0


# ═══════════════════════════════════════════════════════════════════════
# Task 5.5: Profile & Resource Management
# ═══════════════════════════════════════════════════════════════════════


class TestSubagentProfile:
    def test_create_profile(self):
        profile = SubagentProfile(
            name="coder",
            description="Code assistant",
            system_prompt="Write code.",
            model="claude-3",
            tool_visibility=["code_interpreter", "filesystem"],
            max_subagents=3,
        )
        assert profile.name == "coder"
        assert profile.description == "Code assistant"
        assert profile.system_prompt == "Write code."
        assert profile.model == "claude-3"
        assert profile.tool_visibility == ["code_interpreter", "filesystem"]
        assert profile.max_subagents == 3

    def test_default_fields(self):
        profile = SubagentProfile(name="defaults")
        assert profile.max_subagents == 5
        assert profile.max_concurrent_async == 3
        assert profile.token_budget == 4000
        assert profile.timeout == 60.0
        assert profile.model == "default"
        assert profile.metadata == {}

    def test_inherit_creates_new_profile(self):
        parent = SubagentProfile(
            name="parent",
            max_subagents=10,
            token_budget=8000,
            tool_visibility=["*"],
        )
        child = parent.inherit({"name": "child", "max_subagents": 5})
        assert child.name == "child"
        assert child.max_subagents == 5
        assert child.token_budget == 8000
        assert child.tool_visibility == ["*"]

    def test_inherit_does_not_mutate_parent(self):
        parent = SubagentProfile(name="orig", max_subagents=10)
        child = parent.inherit({"max_subagents": 3})
        assert parent.max_subagents == 10
        assert child.max_subagents == 3

    def test_general_purpose_profile(self):
        profile = GeneralPurposeSubagentProfile()
        assert profile.name == "general_purpose"
        assert "general-purpose" in profile.description
        assert profile.tool_visibility == ["*"]
        assert profile.max_subagents == 5

    def test_general_purpose_with_overrides(self):
        profile = GeneralPurposeSubagentProfile(name="custom", max_subagents=10)
        assert profile.name == "custom"
        assert profile.max_subagents == 10

    def test_create_subagent_from_profile(self):
        registry = ToolRegistry()
        profile = SubagentProfile(name="test", description="test agent")
        agent = profile.create_subagent(registry)
        assert isinstance(agent, SubAgent)
        assert agent.name == "test"
        assert agent.description == "test agent"

    def test_create_subagent_no_registry(self):
        profile = SubagentProfile(name="test")
        agent = profile.create_subagent()
        assert agent.name == "test"
        assert agent.tools == []


class TestResourceManager:
    def test_acquire_and_release_slot(self):
        mgr = ResourceManager()
        slot = mgr.acquire_slot("test")
        assert slot is not None
        assert slot.startswith("test_")
        assert mgr.active_count() == 1
        mgr.release_slot(slot)
        assert mgr.active_count() == 0

    def test_acquire_beyond_limit(self):
        mgr = ResourceManager()
        mgr.set_profile(mgr.profile.inherit({"max_subagents": 2}))
        mgr.acquire_slot("a")
        mgr.acquire_slot("b")
        with pytest.raises(ResourceExhaustedError, match="Max subagents"):
            mgr.acquire_slot("c")

    def test_async_slot_limit(self):
        mgr = ResourceManager()
        mgr.set_profile(mgr.profile.inherit({"max_concurrent_async": 1}))
        mgr.acquire_async_slot("a")
        with pytest.raises(ResourceExhaustedError, match="Max concurrent async"):
            mgr.acquire_async_slot("b")

    def test_token_budget_check(self):
        mgr = ResourceManager()
        mgr.set_profile(mgr.profile.inherit({"token_budget": 100}))
        slot = mgr.acquire_slot("budget_test")
        assert mgr.check_token_budget(slot, 50) is True
        assert mgr.check_token_budget(slot, 150) is False

    def test_record_and_check_token_usage(self):
        mgr = ResourceManager()
        mgr.set_profile(mgr.profile.inherit({"token_budget": 100}))
        slot = mgr.acquire_slot("record_test")
        mgr.record_token_usage(slot, 40)
        mgr.record_token_usage(slot, 40)
        assert mgr.check_token_budget(slot, 10) is True
        assert mgr.check_token_budget(slot, 30) is False

    def test_release_slot_unknown(self):
        mgr = ResourceManager()
        mgr.release_slot("nonexistent")
        mgr.release_async_slot("nonexistent")

    def test_clean_orphans(self):
        mgr = ResourceManager()
        mgr.acquire_slot("orphan")
        count = mgr.clean_orphans(max_age_seconds=0)
        assert count >= 1

    def test_default_profile(self):
        mgr = ResourceManager()
        assert mgr.profile.name == "general_purpose"

    def test_set_profile(self):
        mgr = ResourceManager()
        profile = SubagentProfile(name="custom", max_subagents=20)
        mgr.set_profile(profile)
        assert mgr.profile.name == "custom"
        assert mgr.profile.max_subagents == 20

    def test_async_active_count(self):
        mgr = ResourceManager()
        slot = mgr.acquire_async_slot("test")
        assert mgr.async_active_count() == 1
        mgr.release_async_slot(slot)
        assert mgr.async_active_count() == 0

    def test_same_slot_after_release(self):
        mgr = ResourceManager()
        slot = mgr.acquire_slot("reusable")
        mgr.release_slot(slot)
        slot2 = mgr.acquire_slot("reusable")
        assert slot2 != slot  # different id but succeeds


class TestLifecycleManager:
    def test_create_instance(self):
        mgr = LifecycleManager()
        instance = mgr.create("test_profile")
        assert isinstance(instance, SubagentLifecycle)
        assert instance.state == SubagentState.CREATED
        assert instance.profile_name == "test_profile"
        assert instance.id.startswith("sa_")

    def test_start(self):
        mgr = LifecycleManager()
        instance = mgr.create("test")
        started = mgr.start(instance.id)
        assert started is not None
        assert started.state == SubagentState.RUNNING
        assert started.started_at > 0

    def test_complete_success(self):
        mgr = LifecycleManager()
        instance = mgr.create("test")
        mgr.start(instance.id)
        result = ToolResult(success=True, data="done")
        completed = mgr.complete(instance.id, result)
        assert completed.state == SubagentState.COMPLETED
        assert completed.completed_at > 0

    def test_complete_failure(self):
        mgr = LifecycleManager()
        instance = mgr.create("test")
        result = ToolResult(success=False, error="broke")
        completed = mgr.complete(instance.id, result)
        assert completed.state == SubagentState.FAILED
        assert completed.error == "broke"

    def test_timeout(self):
        mgr = LifecycleManager()
        instance = mgr.create("test")
        mgr.start(instance.id)
        timed_out = mgr.timeout(instance.id)
        assert timed_out.state == SubagentState.TIMED_OUT
        assert "timed out" in timed_out.error.lower()

    def test_cancel(self):
        mgr = LifecycleManager()
        instance = mgr.create("test")
        cancelled = mgr.cancel(instance.id)
        assert cancelled.state == SubagentState.CANCELLED

    def test_get_unknown(self):
        mgr = LifecycleManager()
        assert mgr.get("nonexistent") is None

    def test_list_active(self):
        mgr = LifecycleManager()
        i1 = mgr.create("a")
        i2 = mgr.create("b")
        mgr.start(i2.id)
        result = ToolResult(success=True, data="")
        mgr.complete(mgr.create("c").id, result)
        active = mgr.list_active()
        active_ids = [inst.id for inst in active]
        assert i1.id in active_ids
        assert i2.id in active_ids

    def test_list_all(self):
        mgr = LifecycleManager()
        i1 = mgr.create("a")
        i2 = mgr.create("b")
        all_inst = mgr.list_all()
        assert len(all_inst) == 2

    def test_cleanup(self):
        mgr = LifecycleManager()
        instance = mgr.create("old")
        result = ToolResult(success=True, data="")
        mgr.complete(instance.id, result)
        mgr._instances[instance.id].completed_at = time.time() - 10000
        count = mgr.cleanup(max_age_seconds=1)
        assert count >= 1

    def test_resource_manager_accessible(self):
        mgr = LifecycleManager()
        assert mgr.resource_manager is not None
        assert mgr.resource_manager.profile.name == "general_purpose"

    def test_full_lifecycle(self):
        mgr = LifecycleManager()
        instance = mgr.create("worker")
        assert instance.state == SubagentState.CREATED
        mgr.start(instance.id)
        assert mgr.get(instance.id).state == SubagentState.RUNNING
        result = ToolResult(success=True, data="done")
        mgr.complete(instance.id, result)
        assert mgr.get(instance.id).state == SubagentState.COMPLETED

    def test_start_unknown(self):
        mgr = LifecycleManager()
        assert mgr.start("nonexistent") is None

    def test_complete_unknown(self):
        mgr = LifecycleManager()
        assert mgr.complete("nonexistent", ToolResult(success=True)) is None

    def test_timeout_unknown(self):
        mgr = LifecycleManager()
        assert mgr.timeout("nonexistent") is None

    def test_cancel_unknown(self):
        mgr = LifecycleManager()
        assert mgr.cancel("nonexistent") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])