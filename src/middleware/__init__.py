"""Middleware pipeline — Chain-of-Responsibility pattern for agent hooks.

Provides a pluggable middleware stack that intercepts agent lifecycle
events: before/after agent execution, model calls, tool execution, and
more.  Based on DeepAgents' middleware architecture and chatbot-orchestrator's
middleware pipeline.

## Package Structure

- ``types`` — ``AgentMiddleware`` base class, ``ModelRequest``, ``MiddlewareConfig``
- ``stack`` — ``MiddlewareStack`` builder, ``CompiledMiddlewareStack``, ``create_middleware_stack``
- ``summarization`` — ``SummarizationMiddleware``, auto-compact conversation
- ``rubric`` — ``RubricMiddleware``, self-evaluation and grading
- ``tooling`` — Tool middleware (patch, permissions, exclusion, limits, selection)
- ``progress`` — Progress/streaming middleware (first, last, state, todos)
- ``security`` — PII redaction, PIA, injection prevention, audit logging

## Quick Start

.. code-block:: python

    from src.middleware.stack import create_middleware_stack
    from src.middleware.rubric import RubricMiddleware
    from src.middleware.summarization import SummarizationMiddleware

    stack = create_middleware_stack(
        caller_middleware=[
            SummarizationMiddleware(),
            RubricMiddleware(),
        ],
    )
    config = MiddlewareConfig(thread_id="abc123")
    state, halted = stack.run_before_agent(state, runtime, config)

## Middleware Ordering

1. Base: TodoList → PatchToolCalls → ToolSelection → ToolCallLimit
2. Caller: user-provided middleware
3. Tail: profile extra middleware

Overridable via ``MiddlewareProfile`` exclusion and merge strategy.
"""

from src.middleware.progress import (
    AgentCurrentStateMiddleware,
    FirstMiddleware,
    LastMiddleware,
    ProgressMiddleware,
    TodoListMiddleware,
)
from src.middleware.rubric import (
    Criterion,
    CriterionScore,
    CriterionSeverity,
    GradingResult,
    Rubric,
    RubricLibrary,
    RubricMiddleware,
)
from src.middleware.security import (
    AuditMiddleware,
    PIAMiddleware,
    PIIMiddleware,
    SecurityMiddleware,
)
from src.middleware.stack import (
    CompiledMiddlewareStack,
    MiddlewareProfile,
    MiddlewareStack,
    create_middleware_stack,
)
from src.middleware.summarization import (
    SummarizationConfig,
    SummarizationMiddleware,
    TriggerMode,
)
from src.middleware.tooling import (
    FilesystemPermission,
    PatchToolCallsMiddleware,
    PermissionAction,
    PermissionsMiddleware,
    ToolCallLimitMiddleware,
    ToolExclusionMiddleware,
    ToolSelectionMiddleware,
    ToolingMiddleware,
)
from src.middleware.types import (
    AgentMiddleware,
    MiddlewareConfig,
    MiddlewarePosition,
    MiddlewareResult,
    ModelRequest,
)

__all__ = [
    # Base types
    "AgentMiddleware",
    "MiddlewareConfig",
    "MiddlewarePosition",
    "MiddlewareResult",
    "ModelRequest",
    # Stack
    "CompiledMiddlewareStack",
    "MiddlewareProfile",
    "MiddlewareStack",
    "create_middleware_stack",
    # Summarization
    "SummarizationConfig",
    "SummarizationMiddleware",
    "TriggerMode",
    # Rubric
    "Criterion",
    "CriterionScore",
    "CriterionSeverity",
    "GradingResult",
    "Rubric",
    "RubricLibrary",
    "RubricMiddleware",
    # Tooling
    "FilesystemPermission",
    "PatchToolCallsMiddleware",
    "PermissionAction",
    "PermissionsMiddleware",
    "ToolCallLimitMiddleware",
    "ToolExclusionMiddleware",
    "ToolSelectionMiddleware",
    "ToolingMiddleware",
    # Progress
    "AgentCurrentStateMiddleware",
    "FirstMiddleware",
    "LastMiddleware",
    "ProgressMiddleware",
    "TodoListMiddleware",
    # Security
    "AuditMiddleware",
    "PIAMiddleware",
    "PIIMiddleware",
    "SecurityMiddleware",
]