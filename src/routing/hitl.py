"""Human-in-the-loop (HITL) — interrupt, resume, approval, input collection.

Provides:
- ``InterruptSignal`` — signals to pause execution pending human input
- ``ResumeSignal`` — resumes execution from a checkpoint
- ``ApprovalFlow`` — tool execution requiring human approval
- ``InputCollector`` — collect user input mid-execution
- ``HumanInTheLoopMiddleware`` — middleware that intercepts tools
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.middleware.types import AgentMiddleware, MiddlewareConfig
from src.tools.filesystem import ToolResult


# ── Interrupt types ───────────────────────────────────────────────────


class InterruptReason(Enum):
    APPROVAL_REQUIRED = "approval_required"
    INPUT_REQUIRED = "input_required"
    TOOL_APPROVAL = "tool_approval"
    CONFirmation_REQUIRED = "confirmation_required"
    MANUAL_INTERVENTION = "manual_intervention"


@dataclass
class InterruptSignal:
    """Signal to pause execution pending human input.

    Attributes:
        reason: Why execution is paused.
        message: Message to display to the human.
        data: Contextual data for the interrupt.
        interrupt_id: Unique identifier for tracking.
        timeout: Auto-resume timeout in seconds (0 = no timeout).
        allowed_responses: List of valid responses, or None for free text.
        created_at: Timestamp of creation.
    """

    reason: InterruptReason = InterruptReason.INPUT_REQUIRED
    message: str = ""
    data: Any = None
    interrupt_id: str = ""
    timeout: float = 0.0
    allowed_responses: list[str] | None = None
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.interrupt_id:
            self.interrupt_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "interrupt_id": self.interrupt_id,
            "reason": self.reason.value,
            "message": self.message,
            "data": self.data,
            "timeout": self.timeout,
            "allowed_responses": self.allowed_responses,
            "created_at": self.created_at,
        }


# ── Resume signal ─────────────────────────────────────────────────────


@dataclass
class ResumeSignal:
    """Signal to resume execution from an interrupt checkpoint.

    Attributes:
        interrupt_id: Which interrupt this resumes.
        response: Human's response data.
        approved: Whether the action was approved.
        metadata: Additional context from the human.
    """

    interrupt_id: str = ""
    response: Any = None
    approved: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Approval flow ─────────────────────────────────────────────────────


class ApprovalFlow:
    """Manages approval workflows for tool execution.

    Tracks pending approvals, resolves them, and enforces timeout policies.
    """

    def __init__(self) -> None:
        self._pending: dict[str, InterruptSignal] = {}
        self._resolved: dict[str, ResumeSignal] = {}
        self._lock = threading.Lock()

    def request_approval(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        message: str = "",
        timeout: float = 0.0,
    ) -> InterruptSignal:
        """Request approval for a tool execution.

        Args:
            tool_name: The tool requiring approval.
            tool_args: Arguments for the tool.
            message: Explanation for the human.
            timeout: Auto-resume timeout.

        Returns:
            An ``InterruptSignal`` representing the pending approval.
        """
        signal = InterruptSignal(
            reason=InterruptReason.TOOL_APPROVAL,
            message=message or f"Approve execution of '{tool_name}'?",
            data={"tool_name": tool_name, "tool_args": tool_args},
            timeout=timeout,
        )
        with self._lock:
            self._pending[signal.interrupt_id] = signal
        return signal

    def resolve(
        self,
        interrupt_id: str,
        approved: bool,
        response: Any = None,
    ) -> ResumeSignal | None:
        """Resolve a pending approval.

        Args:
            interrupt_id: The interrupt to resolve.
            approved: Whether it was approved.
            response: Optional response data.

        Returns:
            A ``ResumeSignal``, or None if the interrupt wasn't found.
        """
        with self._lock:
            signal = self._pending.pop(interrupt_id, None)
            if signal is None:
                return None
            resume = ResumeSignal(
                interrupt_id=interrupt_id,
                approved=approved,
                response=response,
            )
            self._resolved[interrupt_id] = resume
            return resume

    def check_timeouts(self) -> list[ResumeSignal]:
        """Auto-resolve any timed-out pending approvals.

        Returns:
            List of auto-resolved signals.
        """
        now = time.time()
        resolved: list[ResumeSignal] = []
        with self._lock:
            for interrupt_id, signal in list(self._pending.items()):
                if signal.timeout > 0 and (now - signal.created_at) >= signal.timeout:
                    resume = ResumeSignal(
                        interrupt_id=interrupt_id,
                        approved=False,
                        response=None,
                        metadata={"reason": "timeout"},
                    )
                    self._resolved[interrupt_id] = resume
                    del self._pending[interrupt_id]
                    resolved.append(resume)
        return resolved

    def get_pending(self) -> list[InterruptSignal]:
        with self._lock:
            return list(self._pending.values())

    def get_resolved(self, interrupt_id: str) -> ResumeSignal | None:
        with self._lock:
            return self._resolved.get(interrupt_id)


# ── Input collector ───────────────────────────────────────────────────


class InputCollector:
    """Collects user input mid-execution.

    Raises an interrupt, waits for the human's response,
    then returns it to the execution flow.
    """

    def __init__(self) -> None:
        self._pending_inputs: dict[str, InterruptSignal] = {}
        self._inputs: dict[str, Any] = {}
        self._lock = threading.Lock()

    def request_input(
        self,
        prompt: str,
        allowed_responses: list[str] | None = None,
        timeout: float = 0.0,
    ) -> InterruptSignal:
        """Request input from the human.

        Args:
            prompt: Question or prompt for the human.
            allowed_responses: Restrict to these options.
            timeout: Auto-resume if no response.

        Returns:
            An ``InterruptSignal``.
        """
        signal = InterruptSignal(
            reason=InterruptReason.INPUT_REQUIRED,
            message=prompt,
            allowed_responses=allowed_responses,
            timeout=timeout,
        )
        with self._lock:
            self._pending_inputs[signal.interrupt_id] = signal
        return signal

    def submit_input(self, interrupt_id: str, value: Any) -> bool:
        """Submit input for a pending request.

        Args:
            interrupt_id: The input request to fulfill.
            value: The human's input.

        Returns:
            True if the input was accepted.
        """
        with self._lock:
            if interrupt_id not in self._pending_inputs:
                return False
            del self._pending_inputs[interrupt_id]
            self._inputs[interrupt_id] = value
            return True

    def get_input(self, interrupt_id: str, default: Any = None) -> Any:
        """Get collected input.

        Args:
            interrupt_id: The input request ID.
            default: Fallback value if no input.

        Returns:
            The collected input, or default.
        """
        with self._lock:
            return self._inputs.get(interrupt_id, default)

    def has_pending(self) -> bool:
        with self._lock:
            return len(self._pending_inputs) > 0


# ── HITL middleware ───────────────────────────────────────────────────


class HumanInTheLoopMiddleware(AgentMiddleware):
    """Middleware that intercepts tool calls requiring human approval.

    Configuration:
        ``interrupt_on``: dict mapping tool names to True/False.
        ``timeout``: Default timeout for approvals.
        ``approval_flow``: Shared ``ApprovalFlow`` instance.
        ``input_collector``: Shared ``InputCollector`` instance.
    """

    def __init__(
        self,
        interrupt_on: dict[str, bool] | None = None,
        timeout: float = 0.0,
        approval_flow: ApprovalFlow | None = None,
        input_collector: InputCollector | None = None,
    ) -> None:
        super().__init__()
        self._interrupt_on = interrupt_on or {}
        self._timeout = timeout
        self._approval_flow = approval_flow or ApprovalFlow()
        self._input_collector = input_collector or InputCollector()

    @property
    def approval_flow(self) -> ApprovalFlow:
        return self._approval_flow

    @property
    def input_collector(self) -> InputCollector:
        return self._input_collector

    def set_interrupt(self, tool_name: str, enabled: bool = True) -> None:
        """Enable or disable interrupt for a tool.

        Args:
            tool_name: Name of the tool.
            enabled: True to interrupt, False to allow.
        """
        self._interrupt_on[tool_name] = enabled

    def needs_approval(self, tool_name: str) -> bool:
        """Check if a tool requires approval.

        Args:
            tool_name: Tool to check.

        Returns:
            True if the tool should be interrupted.
        """
        return self._interrupt_on.get(tool_name, False)

    def request_approval(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> InterruptSignal:
        """Request human approval for a tool call.

        Args:
            tool_name: Tool to approve.
            tool_args: Tool arguments.

        Returns:
            An ``InterruptSignal``.
        """
        return self._approval_flow.request_approval(
            tool_name=tool_name,
            tool_args=tool_args,
            message=f"Approve execution of tool '{tool_name}'?",
            timeout=self._timeout,
        )

    async def before_agent(self, config: MiddlewareConfig) -> None:
        pass

    async def after_agent(self, config: MiddlewareConfig) -> None:
        # Auto-resolve timeouts
        self._approval_flow.check_timeouts()

    def get_tools(self) -> list[Any]:
        """Return HITL tools for the agent."""
        return [
            {
                "name": "request_approval",
                "description": "Request human approval before executing a tool. "
                               "Args: tool_name (str), tool_args (dict), message (str, optional)",
            },
            {
                "name": "request_input",
                "description": "Request input from the human user. "
                               "Args: prompt (str), allowed_responses (list, optional)",
            },
            {
                "name": "check_approvals",
                "description": "Check pending approvals and their status.",
            },
        ]


__all__ = [
    "ApprovalFlow",
    "HumanInTheLoopMiddleware",
    "InputCollector",
    "InterruptReason",
    "InterruptSignal",
    "ResumeSignal",
]