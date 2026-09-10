"""Middleware stack builder — assemble, validate, and manage middleware ordering.

Follows the Chain-of-Responsibility pattern.  The stack is built in three
segments:

1. **Base stack** — core middleware (TodoList, Skills, Filesystem, etc.)
2. **Caller middlewares** — user-provided middleware from code/config
3. **Tail stack** — terminal middleware (Memory, HumanInTheLoop, etc.)

Usage::

    stack = MiddlewareStack()
    stack.add(SummarizationMiddleware())
    stack.add(RubricMiddleware())
    compiled = stack.build()
    result = compiled.run(state, runtime, config)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from src.middleware.types import (
    AgentMiddleware,
    AsyncModelCallHandler,
    MiddlewareConfig,
    MiddlewarePosition,
    MiddlewareResult,
    ModelCallHandler,
    ModelRequest,
)

StateT = TypeVar("StateT", bound=dict[str, Any])


# ── Middleware exclusion / merge config ─────────────────────────────────


@dataclass
class MiddlewareProfile:
    """Profile-level middleware configuration.

    Controls which middleware are enabled, which are excluded, and how
    user-supplied middleware merge with the defaults.
    """

    excluded_middleware: list[str] = field(default_factory=list)
    """Middleware names to exclude from the stack."""
    extra_middleware: list[AgentMiddleware[Any]] = field(default_factory=list)
    """Extra middleware to append (added to tail segment)."""
    merge_strategy: str = "replace"
    """How to merge caller middleware: 'replace' or 'append'."""


# ── Middleware stack ─────────────────────────────────────────────────────


class MiddlewareStack(Generic[StateT]):
    """Assembles, validates, and manages middleware ordering.

    The stack maintains three internal lists (base, caller, tail) that
    are flattened at build time.
    """

    def __init__(self) -> None:
        self._base: list[AgentMiddleware[StateT]] = []
        self._caller: list[AgentMiddleware[StateT]] = []
        self._tail: list[AgentMiddleware[StateT]] = []
        self._profile: MiddlewareProfile | None = None

    # ── Public API ─────────────────────────────────────────────────────

    def add(
        self,
        middleware: AgentMiddleware[StateT],
        position: MiddlewarePosition = MiddlewarePosition.CALLER,
    ) -> MiddlewareStack[StateT]:
        """Add a middleware at the given position.

        Args:
            middleware: The middleware instance to add.
            position: Where to place it (base, caller, or tail).

        Returns:
            Self for chaining.
        """
        target = {
            MiddlewarePosition.BASE: self._base,
            MiddlewarePosition.CALLER: self._caller,
            MiddlewarePosition.TAIL: self._tail,
        }[position]
        target.append(middleware)
        return self

    def remove(self, name: str) -> bool:
        """Remove a middleware by name from all segments.

        Args:
            name: The middleware name to remove.

        Returns:
            True if found and removed, False otherwise.
        """
        for segment in (self._base, self._caller, self._tail):
            for i, mw in enumerate(segment):
                if mw.name == name:
                    segment.pop(i)
                    return True
        return False

    def get(self, name: str) -> AgentMiddleware[StateT] | None:
        """Get a middleware by name.

        Args:
            name: The middleware name to find.

        Returns:
            The middleware instance or None.
        """
        for segment in (self._base, self._caller, self._tail):
            for mw in segment:
                if mw.name == name:
                    return mw
        return None

    def set_profile(self, profile: MiddlewareProfile) -> None:
        """Apply a middleware profile.

        This controls exclusion and extra middleware.

        Args:
            profile: The profile to apply.
        """
        self._profile = profile

    def build(self) -> CompiledMiddlewareStack[StateT]:
        """Assemble and validate the middleware stack.

        Applies profile exclusions and extra middleware, then returns
        a ``CompiledMiddlewareStack`` ready for execution.

        Returns:
            A compiled middleware stack.
        """
        # Start with base
        all_mw = list(self._base)

        # Add caller middleware
        if self._profile and self._profile.merge_strategy == "replace":
            all_mw = list(self._base)
            all_mw.extend(self._caller)
        else:
            all_mw.extend(self._caller)

        # Add tail middleware
        all_mw.extend(self._tail)

        # Apply profile exclusions
        if self._profile and self._profile.excluded_middleware:
            excluded = set(self._profile.excluded_middleware)
            all_mw = [m for m in all_mw if m.name not in excluded]

        # Add profile extra middleware
        if self._profile and self._profile.extra_middleware:
            all_mw.extend(self._profile.extra_middleware)

        # Validate
        self._validate(all_mw)

        return CompiledMiddlewareStack(all_mw)

    # ── Factory helpers ───────────────────────────────────────────────

    @classmethod
    def create_default(cls) -> MiddlewareStack[StateT]:
        """Create a middleware stack with the default middleware.

        This mirrors DeepAgents' default stack ordering:

        **Base**: TodoList → Skills → Filesystem → SubAgent → Summarization
                 → PatchToolCalls → AsyncSubAgent

        **Tail**: Profile extra → PromptCaching → Memory → HumanInTheLoop
        """
        from src.middleware.tooling import (
            PatchToolCallsMiddleware,
            ToolCallLimitMiddleware,
            ToolSelectionMiddleware,
        )

        stack = cls()

        # Base stack
        stack.add(
            _LazyMiddleware("todo_list", order=10),
            MiddlewarePosition.BASE,
        )
        stack.add(
            PatchToolCallsMiddleware(),
            MiddlewarePosition.BASE,
        )
        stack.add(
            ToolSelectionMiddleware(),
            MiddlewarePosition.BASE,
        )
        stack.add(
            ToolCallLimitMiddleware(max_calls_per_turn=20),
            MiddlewarePosition.BASE,
        )

        return stack

    # ── Validation ────────────────────────────────────────────────────

    def _validate(self, middleware: list[AgentMiddleware[StateT]]) -> None:
        """Validate the middleware stack.

        Checks:
        - Circular dependencies (not implemented — future).
        - Type consistency.
        - Unique names (duplicates within segment are warned).

        Args:
            middleware: The assembled middleware list.

        Raises:
            ValueError: If validation fails.
        """
        names = [m.name for m in middleware]
        # Check for duplicates
        seen: set[str] = set()
        for name in names:
            if name in seen:
                import warnings

                warnings.warn(f"Duplicate middleware name: {name!r}")
            seen.add(name)


# ── Compiled middleware stack ────────────────────────────────────────────


class CompiledMiddlewareStack(Generic[StateT]):
    """A validated, flattened middleware stack ready for execution.

    The stack is executed in order::

        before_agent:  mw[0].before → mw[1].before → ... → mw[N].before
        after_agent:   mw[N].after → mw[N-1].after → ... → mw[0].after
    """

    def __init__(self, middleware: list[AgentMiddleware[StateT]]) -> None:
        self._middleware = list(middleware)

    @property
    def list(self) -> list[AgentMiddleware[StateT]]:
        """The flattened middleware list."""
        return list(self._middleware)

    @property
    def names(self) -> list[str]:
        """Names of all middleware in order."""
        return [m.name for m in self._middleware]

    # ── Execution ─────────────────────────────────────────────────────

    def run_before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> tuple[dict[str, Any], bool]:
        """Run ``before_agent`` hooks in order.

        Args:
            state: Current agent state.
            runtime: Runtime context.
            config: Runtime configuration.

        Returns:
            ``(state, halted)`` — halted is True if any middleware halted.
        """
        current_state = dict(state)
        for mw in self._middleware:
            result = mw.before_agent(current_state, runtime, config)
            if result is not None:
                if result.state:
                    current_state.update(result.state)
                if result.halt:
                    return current_state, True
        return current_state, False

    def run_after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> dict[str, Any]:
        """Run ``after_agent`` hooks in reverse order.

        Args:
            state: Final agent state.
            runtime: Runtime context.
            config: Runtime configuration.

        Returns:
            Final state after all after_agent hooks.
        """
        current_state = dict(state)
        for mw in reversed(self._middleware):
            result = mw.after_agent(current_state, runtime, config)
            if result is not None and result.state:
                current_state.update(result.state)
        return current_state

    def run_model_chain(
        self,
        request: ModelRequest,
    ) -> Any:
        """Run the model-call chain through all middleware.

        Each middleware's ``wrap_model_call`` can intercept, modify, or
        short-circuit the chain.

        Args:
            request: The model request.

        Returns:
            The model response.
        """

        def _build_chain(
            middleware: list[AgentMiddleware[StateT]],
            index: int,
        ) -> ModelCallHandler[ModelRequest, Any]:
            if index >= len(middleware):
                # Terminal handler — would call the actual LLM
                return lambda req: req
            handler = _build_chain(middleware, index + 1)
            mw = middleware[index]

            def _call(req: ModelRequest) -> Any:
                return mw.wrap_model_call(req, handler)

            return _call

        chain = _build_chain(self._middleware, 0)
        return chain(request)


# ── Lazy middleware placeholder ─────────────────────────────────────────


class _LazyMiddleware(AgentMiddleware[Any]):
    """Placeholder middleware for components not yet implemented.

    This allows the default stack to be assembled without requiring
    all middleware modules to exist.
    """

    def __init__(
        self,
        name: str,
        order: int = 0,
    ) -> None:
        self.name = name
        self.order = order

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        return None


# ── Factory function ────────────────────────────────────────────────────


def create_middleware_stack(
    caller_middleware: list[AgentMiddleware[Any]] | None = None,
    profile: MiddlewareProfile | None = None,
) -> CompiledMiddlewareStack[Any]:
    """Create a fully assembled middleware stack.

    This is the main entry point for building a middleware stack.
    It applies the default stack, caller middleware, profile settings,
    and returns a compiled stack.

    Args:
        caller_middleware: User-provided middleware list.
        profile: Profile-level middleware configuration.

    Returns:
        A compiled middleware stack ready for execution.
    """
    stack = MiddlewareStack.create_default()

    if profile:
        stack.set_profile(profile)

    if caller_middleware:
        for mw in caller_middleware:
            stack.add(mw, MiddlewarePosition.CALLER)

    return stack.build()


__all__ = [
    "CompiledMiddlewareStack",
    "MiddlewareProfile",
    "MiddlewareStack",
    "create_middleware_stack",
]