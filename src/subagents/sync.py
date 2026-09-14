"""Synchronous subagent system.

Allows the main agent to spawn subagents via a ``task`` tool and wait for
results. Subagents run with their own state, tools, and middleware,
and return results as ``ToolMessage`` content.

Inspired by DeepAgents' ``SubAgentMiddleware``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from src.graph.types import Command
from src.middleware.stack import MiddlewareStack
from src.middleware.types import AgentMiddleware, MiddlewareConfig
from src.streaming.execution_log import ExecutionLogger
from src.tools.filesystem import ToolResult
from src.tools.registry import ToolRegistry, ToolSpec


# ── Subagent data types ─────────────────────────────────────────────────


@dataclass
class SubAgent:
    """Declarative subagent specification.

    Defines what a subagent is: its name, system prompt, model,
    tools, and middleware.  Created by the main agent at runtime.
    """

    name: str
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    tools: list[ToolSpec] = field(default_factory=list)
    middleware: list[AgentMiddleware] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompiledSubAgent:
    """A pre-compiled, runnable subagent.

    Created from a ``SubAgent`` spec via ``compile()``.
    Wraps the actual execution logic.
    """

    spec: SubAgent
    _executor: Callable[[dict[str, Any]], ToolResult] | None = None
    _execution_logger: ExecutionLogger | None = None

    def set_execution_logger(self, logger: ExecutionLogger) -> None:
        """Attach an execution logger for step-by-step tracing."""
        self._execution_logger = logger

    def invoke(self, input_data: dict[str, Any]) -> ToolResult:
        """Run the subagent with the given input.

        Args:
            input_data: Input state to pass to the subagent.

        Returns:
            ``ToolResult`` with the subagent's output.
        """
        if self._executor:
            return self._executor(input_data)

        # ── Log subagent execution start ──────────────────────────────
        exec_log = self._execution_logger
        step = None
        if exec_log is not None:
            step = exec_log.start_step(
                node_name=f"subagent:{self.spec.name}",
                node_type="subagent",
                input_state=input_data if isinstance(input_data, dict) else {"input": str(input_data)[:200]},
                metadata={"model": self.spec.model, "tools": [t.name for t in self.spec.tools]},
            )

        # Default execution: run middleware chain then return
        middleware_stack = MiddlewareStack()
        for mw in self.spec.middleware:
            middleware_stack.add(mw)

        compiled = middleware_stack.build()

        # Run middleware before_agent
        config = MiddlewareConfig()
        config.configurable["system_prompt"] = self.spec.system_prompt
        config.configurable["subagent_name"] = self.spec.name

        try:
            state, _ = compiled.run_before_agent(input_data, None, config)

            result = ToolResult(
                success=True,
                data=f"SubAgent '{self.spec.name}' executed",
                metadata={"subagent": self.spec.name, "state": state},
            )

            # ── Log success ───────────────────────────────────────────
            if exec_log and step is not None:
                exec_log.complete_step(
                    step,
                    output_preview=f"SubAgent '{self.spec.name}' completed",
                    metadata={"state_keys": list(state.keys())[:10]},
                )

            return result

        except Exception as e:
            # ── Log failure ───────────────────────────────────────────
            if exec_log and step is not None:
                exec_log.fail_step(
                    step,
                    error=e,
                    metadata={"subagent": self.spec.name},
                )

            return ToolResult(
                success=False,
                error=f"SubAgent '{self.spec.name}' failed: {e}",
            )


# ── Subagent registry ───────────────────────────────────────────────────


class SubAgentRegistry:
    """Registry for managing subagent specs and compiled instances."""

    def __init__(self) -> None:
        self._specs: dict[str, SubAgent] = {}
        self._compiled: dict[str, CompiledSubAgent] = {}

    def register(self, spec: SubAgent) -> CompiledSubAgent:
        """Register a subagent spec and return its compiled form.

        Args:
            spec: Subagent specification.

        Returns:
            Compiled subagent ready for invocation.
        """
        self._specs[spec.name] = spec
        compiled = CompiledSubAgent(spec=spec)
        self._compiled[spec.name] = compiled
        return compiled

    def get(self, name: str) -> CompiledSubAgent | None:
        """Get a compiled subagent by name."""
        return self._compiled.get(name)

    def get_spec(self, name: str) -> SubAgent | None:
        """Get a subagent spec by name."""
        return self._specs.get(name)

    def unregister(self, name: str) -> bool:
        """Remove a subagent.

        Returns:
            True if it existed.
        """
        self._specs.pop(name, None)
        return self._compiled.pop(name, None) is not None

    def list(self) -> list[SubAgent]:
        """List all registered subagent specs."""
        return list(self._specs.values())


# ── Default general-purpose subagent ────────────────────────────────────

DEFAULT_SUBAGENT_SPEC = SubAgent(
    name="general_purpose",
    description="A general-purpose assistant that can help with any task.",
    system_prompt="You are a helpful assistant.",
    model="default",
)


# ── Task tool ───────────────────────────────────────────────────────────


class SubAgentMiddleware(AgentMiddleware):
    """Middleware that registers a ``task`` tool for the main agent.

    The ``task`` tool lets the main agent spawn subagents by name,
    pass input data, and receive results back.
    """

    def __init__(
        self,
        registry: SubAgentRegistry | None = None,
        propagation_fields: list[str] | None = None,
        execution_logger: ExecutionLogger | None = None,
    ) -> None:
        super().__init__()
        self._registry = registry or SubAgentRegistry()
        self._propagation_fields = propagation_fields or []
        self._execution_logger = execution_logger

        # Register default subagent
        self._registry.register(DEFAULT_SUBAGENT_SPEC)

        # Propagate execution logger to all compiled subagents
        if execution_logger is not None:
            for compiled in self._registry._compiled.values():
                compiled.set_execution_logger(execution_logger)

    @property
    def registry(self) -> SubAgentRegistry:
        return self._registry

    def set_execution_logger(self, logger: ExecutionLogger) -> None:
        """Set or update the execution logger for all subagents."""
        self._execution_logger = logger
        for compiled in self._registry._compiled.values():
            compiled.set_execution_logger(logger)

    async def before_agent(self, config: MiddlewareConfig) -> None:
        pass

    async def after_agent(self, config: MiddlewareConfig) -> None:
        pass

    def task_tool_fn(self) -> Callable[..., ToolResult]:
        """Return the ``task`` tool function.

        The main agent calls this tool with a subagent name and input,
        and receives the subagent's result.

        Args:
            name: Subagent name to invoke.
            input: Input data as a dict or string.

        Returns:
            ``ToolResult`` with the subagent's output.
        """

        def _task(name: str, input_data: Any = None) -> ToolResult:
            compiled = self._registry.get(name)
            if compiled is None:
                return ToolResult(
                    success=False,
                    error=f"Unknown subagent: '{name}'. Available: {[s.name for s in self._registry.list()]}",
                )
            return compiled.invoke({"input": input_data})

        _task.__name__ = "task"
        _task.__doc__ = "Execute a subagent by name and return its result. Args: name (str): subagent name, input (optional): input data."
        return _task

    def get_task_tool_spec(self) -> ToolSpec:
        """Get a ``ToolSpec`` for the ``task`` tool."""
        fn = self.task_tool_fn()
        return ToolSpec(
            name="task",
            description="Execute a named subagent and return its result. Use this to delegate tasks to specialized sub-agents.",
            fn=fn,
            category="subagent",
            tags=["subagent", "communication"],
        )


__all__ = [
    "CompiledSubAgent",
    "DEFAULT_SUBAGENT_SPEC",
    "SubAgent",
    "SubAgentMiddleware",
    "SubAgentRegistry",
]