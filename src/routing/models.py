"""Model routing & fallback — route tasks to models and handle failures.

Provides a ModelRouter that selects models based on task type, cost,
and availability, with automatic fallback on failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Categories of tasks that can be routed to different models."""

    CHAT = "chat"
    """General conversation."""

    CODE = "code"
    """Code generation and analysis."""

    REASONING = "reasoning"
    """Complex reasoning, math, logic."""

    CREATIVE = "creative"
    """Creative writing, brainstorming."""

    SUMMARIZATION = "summarization"
    """Text summarization."""

    EXTRACTION = "extraction"
    """Information extraction."""

    CLASSIFICATION = "classification"
    """Text classification."""

    EMBEDDING = "embedding"
    """Text embedding."""

    RESEARCH = "research"
    """Deep research tasks."""

    TOOL_CALLING = "tool_calling"
    """Tasks requiring tool use."""


@dataclass
class ModelConfig:
    """Configuration for a single model."""

    name: str
    """Model identifier (e.g. 'gpt-4o', 'claude-sonnet-4')."""

    provider: str = ""
    """Provider name (e.g. 'openai', 'anthropic')."""

    task_types: list[TaskType] = field(default_factory=list)
    """Task types this model is suitable for."""

    cost_per_1k_input: float = 0.0
    """Cost in USD per 1K input tokens."""

    cost_per_1k_output: float = 0.0
    """Cost in USD per 1K output tokens."""

    context_window: int = 8192
    """Maximum context window in tokens."""

    priority: int = 0
    """Higher priority models are preferred."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional configuration."""


@dataclass
class RoutingResult:
    """Result of a routing decision."""

    chosen_model: str
    """The selected model name."""

    task_type: TaskType
    """The task type that was routed."""

    fallback_used: bool = False
    """Whether a fallback model was selected."""

    fallback_chain: list[str] = field(default_factory=list)
    """The chain of models tried before succeeding."""

    estimated_cost: float = 0.0
    """Estimated cost for this routing decision."""

    reason: str = ""
    """Why this model was chosen."""


InvokeFn = Callable[..., Any]


class ModelRouter:
    """Routes tasks to models based on type, cost, and availability.

    Maintains a prioritized list of models per task type and handles
    automatic fallback when a model is unavailable or fails.
    """

    def __init__(
        self,
        models: list[ModelConfig] | None = None,
        default_model: str = "",
    ) -> None:
        """Initialize the router.

        Args:
            models: List of available model configurations.
            default_model: Fallback model name when no other match.
        """
        self._models: dict[str, ModelConfig] = {}
        self._task_type_map: dict[TaskType, list[str]] = {
            tt: [] for tt in TaskType
        }
        if models:
            for mc in models:
                self.add_model(mc)
        self._default_model = default_model

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def add_model(self, config: ModelConfig) -> None:
        """Register a model configuration."""
        self._models[config.name] = config
        for task_type in config.task_types:
            if config.name not in self._task_type_map[task_type]:
                self._task_type_map[task_type].append(config.name)
                # Keep sorted by priority descending
                self._task_type_map[task_type].sort(
                    key=lambda n: self._models[n].priority,
                    reverse=True,
                )

    def remove_model(self, name: str) -> None:
        """Remove a model from the registry."""
        self._models.pop(name, None)
        for task_type in TaskType:
            self._task_type_map[task_type] = [
                n for n in self._task_type_map[task_type] if n != name
            ]

    def get_model(self, name: str) -> ModelConfig | None:
        """Get a model's configuration."""
        return self._models.get(name)

    def list_models(self, task_type: TaskType | None = None) -> list[ModelConfig]:
        """List registered models, optionally filtered by task type."""
        if task_type is not None:
            names = self._task_type_map.get(task_type, [])
            return [self._models[n] for n in names if n in self._models]
        return list(self._models.values())

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route(
        self,
        task_type: TaskType,
        constraints: dict[str, Any] | None = None,
    ) -> RoutingResult:
        """Select the best model for a task type.

        Args:
            task_type: The type of task to route.
            constraints: Optional constraints:
                - 'max_cost': float — maximum cost per 1K input tokens
                - 'min_context': int — minimum context window
                - 'preferred_model': str — specific model to try first

        Returns:
            A RoutingResult with the decision.
        """
        candidates = self._task_type_map.get(task_type, [])
        constraints = constraints or {}

        preferred = constraints.get("preferred_model")
        max_cost = constraints.get("max_cost")
        min_context = constraints.get("min_context")

        # Always try the preferred model first
        if preferred and preferred in self._models:
            if self._model_satisfies(preferred, max_cost, min_context):
                return RoutingResult(
                    chosen_model=preferred,
                    task_type=task_type,
                    reason="Preferred model chosen",
                )

        # Try candidates in priority order
        fallback_chain: list[str] = []
        for name in candidates:
            config = self._models.get(name)
            if config is None:
                continue
            if not self._model_satisfies(name, max_cost, min_context):
                fallback_chain.append(name)
                continue
            return RoutingResult(
                chosen_model=name,
                task_type=task_type,
                fallback_used=len(fallback_chain) > 0,
                fallback_chain=fallback_chain,
                estimated_cost=config.cost_per_1k_input,
                reason=f"Best match for {task_type.value}",
            )

        # Fallback to default
        if self._default_model and self._default_model in self._models:
            return RoutingResult(
                chosen_model=self._default_model,
                task_type=task_type,
                fallback_used=True,
                fallback_chain=fallback_chain,
                reason=f"Default model chosen after {len(fallback_chain)} fallbacks",
            )

        # Last resort: any registered model
        if self._models:
            any_model = next(iter(self._models.values()))
            return RoutingResult(
                chosen_model=any_model.name,
                task_type=task_type,
                fallback_used=True,
                fallback_chain=fallback_chain,
                reason="Last resort: no explicit match found",
            )

        raise RuntimeError(f"No model available for task type {task_type}")

    def invoke_with_fallback(
        self,
        task_type: TaskType,
        invoke_fn: InvokeFn,
        max_retries: int = 2,
        constraints: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke a model with automatic fallback on failure.

        Tries models in priority order. If the first model fails, it
        falls back to the next available model for the task type.

        Args:
            task_type: The task type.
            invoke_fn: Callable(model_name, **kwargs) that invokes the model.
            max_retries: Maximum number of fallback attempts.
            constraints: Routing constraints.
            **kwargs: Passed to invoke_fn.

        Returns:
            The result of the successful invocation.

        Raises:
            RuntimeError: If all models fail.
        """
        models_to_try = list(self._task_type_map.get(task_type, []))
        preferred = (constraints or {}).get("preferred_model")
        if preferred and preferred in models_to_try:
            models_to_try.remove(preferred)
            models_to_try.insert(0, preferred)

        last_error: Exception | None = None
        attempts = 0

        for model_name in models_to_try:
            if attempts >= max_retries:
                break
            try:
                return invoke_fn(model_name=model_name, **kwargs)
            except Exception as exc:
                attempts += 1
                last_error = exc
                logger.warning(
                    "Model %s failed for %s (attempt %d): %s",
                    model_name,
                    task_type.value,
                    attempts,
                    exc,
                )

        raise RuntimeError(
            f"All models failed for task {task_type.value} after {attempts} attempts"
        ) from last_error

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def estimate_cost(
        self,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> float:
        """Estimate the cost of using a model.

        Args:
            model_name: The model name.
            input_tokens: Approximate input token count.
            output_tokens: Approximate output token count.

        Returns:
            Estimated cost in USD.
        """
        config = self._models.get(model_name)
        if config is None:
            return 0.0

        input_cost = (input_tokens / 1000) * config.cost_per_1k_input
        output_cost = (output_tokens / 1000) * config.cost_per_1k_output
        return round(input_cost + output_cost, 6)

    def cheapest_model_for(self, task_type: TaskType) -> str | None:
        """Get the cheapest available model for a task type."""
        names = self._task_type_map.get(task_type, [])
        best: tuple[str, float] | None = None
        for name in names:
            config = self._models.get(name)
            if config is None:
                continue
            rate = config.cost_per_1k_input + config.cost_per_1k_output
            if best is None or rate < best[1]:
                best = (name, rate)
        return best[0] if best else None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _model_satisfies(
        self,
        name: str,
        max_cost: float | None,
        min_context: int | None,
    ) -> bool:
        config = self._models.get(name)
        if config is None:
            return False
        if max_cost is not None and config.cost_per_1k_input > max_cost:
            return False
        if min_context is not None and config.context_window < min_context:
            return False
        return True