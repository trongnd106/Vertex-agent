"""Routing, control flow, and orchestration for agent execution.

Sub-packages and modules:

- ``conditional`` — RouteCondition, ConditionalRouter, DynamicRouter, MapReduceRouter
- ``loops`` — LoopController, ForLoop, WhileLoop, RecursionLimit, LoopDetector
- ``hitl`` — InterruptSignal, ResumeSignal, ApprovalFlow, HumanInTheLoopMiddleware
- ``workflow`` — Task, TaskDispatcher, HandlerRegistry, Workflow, TaskTree
- ``events`` — SystemEvent, EventBus, CircuitBreaker, CentralizedErrorHandler, RetryHandler
"""

from src.routing.models import (
    ModelConfig,
    ModelRouter,
    RoutingResult,
    TaskType,
)
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
    Handler,
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

__all__ = [
    # models
    "ModelConfig",
    "ModelRouter",
    "RoutingResult",
    "TaskType",
    # conditional
    "BranchSpec",
    "ConditionalRouter",
    "DynamicRouter",
    "MapReduceRouter",
    "PathMap",
    "RouteCondition",
    # loops
    "ForLoop",
    "LoopAction",
    "LoopController",
    "LoopDetector",
    "MapLoop",
    "NestedLoop",
    "RecursionLimit",
    "WhileLoop",
    # hitl
    "ApprovalFlow",
    "HumanInTheLoopMiddleware",
    "InputCollector",
    "InterruptReason",
    "InterruptSignal",
    "ResumeSignal",
    # workflow
    "Handler",
    "HandlerRegistry",
    "Task",
    "TaskDispatcher",
    "TaskResult",
    "TaskStatus",
    "TaskTree",
    "Workflow",
    "WorkflowResult",
    "WorkflowStep",
    "WorkflowStepStatus",
    # events
    "CentralizedErrorHandler",
    "CircuitBreaker",
    "CircuitState",
    "ErrorCategory",
    "ErrorClassifier",
    "ErrorResponse",
    "ErrorSeverity",
    "EventBus",
    "EventType",
    "MessageQueueEventProducer",
    "RetryHandler",
    "SystemEvent",
]