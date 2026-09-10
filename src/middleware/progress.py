"""Progress and streaming middleware — track agent state, emit progress events.

Provides middleware for the streaming pipeline:

- ``FirstMiddleware`` — sends initialisation messages, sets session markers
- ``AgentCurrentStateMiddleware`` — tracks current agent state
- ``TodoListMiddleware`` — ``write_todos`` tool for agent task lists
- ``ProgressMiddleware`` — emits progress events through the streaming pipeline
- ``LastMiddleware`` — finalises the stream, sends completion messages

Inspired by orchestrator's ``first_middleware.py``,
``agent_current_state.py``, ``todo.py``, and ``last_middleware.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from src.middleware.types import (
    AgentMiddleware,
    MiddlewareConfig,
    MiddlewareResult,
)


# ── Agent state tracking ─────────────────────────────────────────────────


class AgentState(Enum):
    """Tracks the current state of the agent."""

    INITIALIZING = auto()
    """Agent is starting up."""
    THINKING = auto()
    """Agent is processing / calling model."""
    WAITING_FOR_TOOL = auto()
    """Agent is waiting for a tool result."""
    RESPONDING = auto()
    """Agent is generating a response."""
    COMPLETED = auto()
    """Agent has finished."""
    ERROR = auto()
    """Agent encountered an error."""


@dataclass
class TodoItem:
    """A task item in the agent's todo list."""

    id: str
    """Unique identifier."""
    description: str
    """Task description."""
    status: str = "pending"
    """Status: pending, in_progress, completed, failed."""
    created_at: float = 0.0
    """Creation timestamp."""
    completed_at: float | None = None
    """Completion timestamp."""


# ── FirstMiddleware ──────────────────────────────────────────────────────


class FirstMiddleware(AgentMiddleware[Any]):
    """Sends initialization messages and sets session markers.

    This middleware runs first in the base stack.  It sets up the session
    and emits a "started" event.
    """

    name = "first"

    def __init__(self) -> None:
        super().__init__()
        self._start_time: float = 0.0

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Initialise session and emit start event."""
        self._start_time = time.monotonic()

        # Set session markers
        state["_session_started"] = True
        state["_agent_state"] = AgentState.INITIALIZING.name.lower()

        # Emit start event
        if config.stream_callback:
            config.stream_callback(
                {
                    "type": "session_start",
                    "thread_id": config.thread_id,
                    "timestamp": self._start_time,
                    "tags": config.tags,
                }
            )

        if config.debug:
            print(f"[FirstMiddleware] Session started: {config.thread_id}")

        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Clean up session markers."""
        state["_session_started"] = False
        return None


# ── AgentCurrentStateMiddleware ──────────────────────────────────────────


class AgentCurrentStateMiddleware(AgentMiddleware[Any]):
    """Tracks the current state of the agent throughout execution.

    Updates ``_agent_state`` in state as the agent progresses.
    """

    name = "agent_current_state"

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Set state to thinking."""
        state["_agent_state"] = AgentState.THINKING.name.lower()
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Determine final state based on messages."""
        messages = state.get("messages", [])
        if messages:
            last = messages[-1]
            if isinstance(last, dict):
                if "tool_calls" in last and last["tool_calls"]:
                    state["_agent_state"] = AgentState.WAITING_FOR_TOOL.name.lower()
                else:
                    state["_agent_state"] = AgentState.RESPONDING.name.lower()

        # Emit state update
        if config.stream_callback:
            config.stream_callback(
                {
                    "type": "agent_state",
                    "state": state.get("_agent_state"),
                }
            )

        return None


# ── TodoListMiddleware ───────────────────────────────────────────────────


class TodoListMiddleware(AgentMiddleware[Any]):
    """Adds a ``write_todos`` tool for the agent's task list.

    The agent can use this tool to maintain a visible todo list
    displayed to the user via the streaming pipeline.
    """

    name = "todo_list"

    def __init__(self) -> None:
        super().__init__()
        self._todos: dict[str, TodoItem] = {}
        self._next_id: int = 0

    @property
    def todos(self) -> list[TodoItem]:
        """Current todo list."""
        return list(self._todos.values())

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Inject todo list into state."""
        state["_todos"] = [t.__dict__ for t in self._todos.values()]
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Check for tool call results that update todos."""
        messages = state.get("messages", [])
        if not messages:
            return None

        # Look for write_todos tool results
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "tool":
                content = msg.get("content", "")
                if "TODO" in content.upper():
                    self._parse_todo_content(content)

        # Update state with current todos
        state["_todos"] = [t.__dict__ for t in self._todos.values()]

        return None

    def write_todos(
        self,
        items: list[dict[str, str]],
    ) -> str:
        """Tool: Write or update todo items.

        Each item should have a 'description' and optional 'status'.

        Args:
            items: List of todo item dicts.

        Returns:
            Confirmation message.
        """
        for item in items:
            todo_id = item.get("id", f"todo_{self._next_id}")
            self._next_id += 1

            if todo_id in self._todos:
                # Update existing
                existing = self._todos[todo_id]
                existing.status = item.get("status", existing.status)
                if existing.status == "completed" and not existing.completed_at:
                    existing.completed_at = time.monotonic()
            else:
                # Create new
                self._todos[todo_id] = TodoItem(
                    id=todo_id,
                    description=item.get("description", ""),
                    status=item.get("status", "pending"),
                    created_at=time.monotonic(),
                )

        return f"Updated {len(items)} todo items. Current: {len(self._todos)} total."

    def _parse_todo_content(self, content: str) -> None:
        """Parse todo items from a content string.

        Looks for lines matching: ``TODO: description [status]``

        Args:
            content: Text content to parse.
        """
        import re as _re

        for line in content.split("\n"):
            match = _re.match(r"\s*TODO:\s*(.+?)(?:\s+\[(\w+)\])?\s*$", line)
            if match:
                description = match.group(1).strip()
                status = match.group(2) or "pending"
                self.write_todos([{"description": description, "status": status}])


# ── ProgressMiddleware ───────────────────────────────────────────────────


class ProgressMiddleware(AgentMiddleware[Any]):
    """Emits progress events through the streaming pipeline.

    Tracks step-level progress and emits events that the streaming
    pipeline can forward to the user interface.
    """

    name = "progress"

    def __init__(self) -> None:
        super().__init__()
        self._step: int = 0

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Emit a progress event for the current step."""
        self._step += 1

        if config.stream_callback:
            config.stream_callback(
                {
                    "type": "progress",
                    "step": self._step,
                    "agent_state": state.get("_agent_state", "unknown"),
                    "timestamp": time.monotonic(),
                }
            )

        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Emit a completion progress event."""
        if config.stream_callback:
            config.stream_callback(
                {
                    "type": "progress",
                    "step": self._step,
                    "status": "completed",
                    "timestamp": time.monotonic(),
                }
            )
        return None


# ── LastMiddleware ───────────────────────────────────────────────────────


class LastMiddleware(AgentMiddleware[Any]):
    """Finalises the stream and sends a completion message.

    This middleware runs last in the tail stack.  It emits the final
    stream event and cleans up.
    """

    name = "last"

    def __init__(self) -> None:
        super().__init__()
        self._start_time: float = 0.0

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Record start time."""
        self._start_time = time.monotonic()
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Emit session end event."""
        elapsed = time.monotonic() - self._start_time

        # Determine completion status
        error = state.get("_error")
        status = "error" if error else "completed"

        if config.stream_callback:
            config.stream_callback(
                {
                    "type": "session_end",
                    "status": status,
                    "elapsed_seconds": elapsed,
                    "error": str(error) if error else None,
                }
            )

        if config.debug:
            print(f"[LastMiddleware] Session ended: {status} in {elapsed:.2f}s")

        # Clean up internal state keys
        for key in list(state.keys()):
            if key.startswith("_"):
                if key not in ("_summary", "_todos", "_rubric_feedback"):
                    pass  # Keep for downstream introspection

        return None


__all__ = [
    "AgentCurrentStateMiddleware",
    "AgentState",
    "FirstMiddleware",
    "LastMiddleware",
    "ProgressMiddleware",
    "TodoItem",
    "TodoListMiddleware",
]