"""Subagent communication system.

This package provides agents with the ability to spawn, communicate,
and coordinate with sub-agents. It supports synchronous and asynchronous
subagent patterns, inter-agent messaging, parallel tool execution,
and profile-based resource management.

Subpackages:
    sync        — Synchronous subagent system (SubAgent, CompiledSubAgent).
    async_sub   — Async subagent system with remote deployment.
    communication — Inter-agent messaging, event bus, shared state.
    parallel    — Parallel tool execution via ThreadPoolExecutor.
    profiles    — Subagent profiles, resource & lifecycle management.

Usage:
    from src.subagents import SubAgent, CompiledSubAgent, SubAgentRegistry
    from src.subagents import SubAgentProfile, LifecycleManager
    from src.subagents import MessageBroker, EventBus
    from src.subagents import ParallelExecutor
"""

from src.subagents.sync import (
    CompiledSubAgent,
    DEFAULT_SUBAGENT_SPEC,
    SubAgent,
    SubAgentMiddleware,
    SubAgentRegistry,
)
from src.subagents.async_sub import (
    AsyncSubAgent,
    AsyncSubAgentManager,
    AsyncSubAgentMiddleware,
    AsyncSubAgentStatus,
    AsyncTask,
)
from src.subagents.communication import (
    AgentEvent,
    AgentMessage,
    CommunicationMiddleware,
    EventBus,
    MessageBroker,
    MessageType,
    SharedState,
)
from src.subagents.parallel import (
    BatchResult,
    ParallelExecutor,
    ParallelToolCall,
    ParallelToolResult,
)
from src.subagents.profiles import (
    GeneralPurposeSubagentProfile,
    SubagentLifecycle,
    SubagentProfile,
    SubagentState,
    ResourceManager,
    LifecycleManager,
    ResourceExhaustedError,
)

__all__ = [
    # sync
    "CompiledSubAgent",
    "DEFAULT_SUBAGENT_SPEC",
    "SubAgent",
    "SubAgentMiddleware",
    "SubAgentRegistry",
    # async
    "AsyncSubAgent",
    "AsyncSubAgentManager",
    "AsyncSubAgentMiddleware",
    "AsyncSubAgentStatus",
    "AsyncTask",
    # communication
    "AgentEvent",
    "AgentMessage",
    "CommunicationMiddleware",
    "EventBus",
    "MessageBroker",
    "MessageType",
    "SharedState",
    # parallel
    "BatchResult",
    "ParallelExecutor",
    "ParallelToolCall",
    "ParallelToolResult",
    # profiles
    "GeneralPurposeSubagentProfile",
    "SubagentLifecycle",
    "SubagentProfile",
    "SubagentState",
    "ResourceManager",
    "LifecycleManager",
    "ResourceExhaustedError",
]