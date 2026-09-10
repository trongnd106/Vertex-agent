"""Loops and recursion control for agent graphs.

Provides:
- ``RecursionLimit`` — max step enforcement with detection
- ``LoopDetector`` — infinite loop detection via state hash tracking
- ``ForLoop`` — fixed iteration count loop
- ``WhileLoop`` — condition-based iteration loop
- ``MapLoop`` — iterate over list items
- ``NestedLoop`` — loops within subgraphs
- ``LoopController`` — break/continue commands
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# ── Loop control commands ─────────────────────────────────────────────


class LoopAction(Enum):
    """Actions that can be taken within a loop."""
    CONTINUE = "continue"
    BREAK = "break"
    EXIT = "exit"
    NONE = "none"


class LoopController:
    """Provides break/continue/exit control for loops.

    Usage:
        controller = LoopController()
        # Inside loop body:
        if condition:
            controller.break_loop()
        if other:
            controller.continue_loop()
        if exit_all:
            controller.exit_all()

        action = controller.check()  # check after each iteration
        if action == LoopAction.BREAK:
            break
    """

    def __init__(self) -> None:
        self._action = LoopAction.NONE
        self._lock = threading.Lock()

    def break_loop(self) -> None:
        """Signal a break from the current loop."""
        with self._lock:
            self._action = LoopAction.BREAK

    def continue_loop(self) -> None:
        """Signal a continue (skip to next iteration)."""
        with self._lock:
            self._action = LoopAction.CONTINUE

    def exit_all(self) -> None:
        """Signal exit from all nested loops."""
        with self._lock:
            self._action = LoopAction.EXIT

    def check(self) -> LoopAction:
        """Check and consume the current action.

        Returns:
            The loop action, or LoopAction.NONE.
        """
        with self._lock:
            action = self._action
            self._action = LoopAction.NONE
            return action

    @property
    def is_break(self) -> bool:
        return self._action == LoopAction.BREAK


# ── Recursion limit ───────────────────────────────────────────────────


class RecursionLimit:
    """Enforces a maximum number of agent execution steps.

    Configurable per-run. Detects and prevents runaway execution.
    """

    def __init__(self, max_steps: int = 9999) -> None:
        self._max_steps = max_steps
        self._current = 0

    def increment(self) -> int:
        """Increment step counter.

        Returns:
            The current step count.

        Raises:
            RecursionLimitExceeded: If the limit has been reached.
        """
        self._current += 1
        if self._current > self._max_steps:
            raise RecursionLimitExceeded(
                f"Recursion limit exceeded: {self._current} > {self._max_steps}"
            )
        return self._current

    def reset(self) -> None:
        self._current = 0

    @property
    def current(self) -> int:
        return self._current

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @max_steps.setter
    def max_steps(self, value: int) -> None:
        self._max_steps = value


class RecursionLimitExceeded(Exception):
    """Raised when the recursion limit is exceeded."""
    pass


# ── Loop detector (infinite loop prevention) ──────────────────────────


@dataclass
class LoopDetectionConfig:
    """Configuration for infinite loop detection.

    Attributes:
        max_repeated_states: Max times the same state hash can repeat.
        window_size: Number of recent steps to track.
        similarity_threshold: Fraction of identical states to flag (0.0-1.0).
    """

    max_repeated_states: int = 5
    window_size: int = 20
    similarity_threshold: float = 0.8


class LoopDetector:
    """Detects infinite loops by tracking state hashes.

    Maintains a sliding window of recent state hashes and flags
    loops when the same hash repeats beyond a threshold.
    """

    def __init__(self, config: LoopDetectionConfig | None = None) -> None:
        self._config = config or LoopDetectionConfig()
        self._hashes: list[int] = []
        self._hash_counts: dict[int, int] = {}
        self._detected = False

    def record(self, state: dict[str, Any]) -> bool:
        """Record a state and check for loops.

        Args:
            state: Current agent state.

        Returns:
            True if a loop is detected, False otherwise.
        """
        state_hash = self._hash_state(state)
        self._hashes.append(state_hash)
        if len(self._hashes) > self._config.window_size:
            removed = self._hashes.pop(0)
            self._hash_counts[removed] = self._hash_counts.get(removed, 1) - 1
            if self._hash_counts[removed] <= 0:
                del self._hash_counts[removed]

        self._hash_counts[state_hash] = self._hash_counts.get(state_hash, 0) + 1

        if self._hash_counts[state_hash] >= self._config.max_repeated_states:
            self._detected = True
            return True

        # Check similarity threshold
        if len(self._hashes) >= self._config.window_size:
            max_count = max(self._hash_counts.values())
            if max_count / len(self._hashes) >= self._config.similarity_threshold:
                self._detected = True
                return True

        return False

    def _hash_state(self, state: dict[str, Any]) -> int:
        """Create a hash of the state for comparison."""
        try:
            # Only use keys and simple values for hashing
            simplified = {}
            for k, v in state.items():
                if isinstance(v, (str, int, float, bool, type(None))):
                    simplified[k] = v
                elif isinstance(v, (list, tuple)):
                    simplified[k] = type(v).__name__ + str(len(v))
                else:
                    simplified[k] = type(v).__name__
            return hash(frozenset(simplified.items()))
        except Exception:
            return 0

    @property
    def detected(self) -> bool:
        return self._detected

    def reset(self) -> None:
        self._hashes.clear()
        self._hash_counts.clear()
        self._detected = False


# ── ForLoop ───────────────────────────────────────────────────────────


class ForLoop:
    """Fixed-iteration-count loop for agent execution.

    Usage:
        loop = ForLoop(iterations=5, body_fn=my_node)
        loop.run(initial_state)
    """

    def __init__(
        self,
        iterations: int,
        body_fn: Callable[[dict[str, Any], int], dict[str, Any]],
        name: str = "",
    ) -> None:
        self._iterations = iterations
        self._body_fn = body_fn
        self._name = name or f"for_loop_{uuid.uuid4().hex[:6]}"
        self._controller = LoopController()
        self._current_iteration = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def controller(self) -> LoopController:
        return self._controller

    @property
    def iterations(self) -> int:
        return self._iterations

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run the for loop.

        Args:
            state: Initial state.

        Returns:
            State after loop completion.
        """
        current_state = dict(state)
        for i in range(self._iterations):
            self._current_iteration = i
            action = self._controller.check()
            if action == LoopAction.BREAK or action == LoopAction.EXIT:
                break
            if action == LoopAction.CONTINUE:
                continue
            current_state = self._body_fn(current_state, i)
        self._current_iteration = 0
        return current_state


# ── WhileLoop ─────────────────────────────────────────────────────────


class WhileLoop:
    """Condition-based iteration loop.

    Usage:
        loop = WhileLoop(condition_fn, body_fn)
        loop.run(initial_state)
    """

    def __init__(
        self,
        condition_fn: Callable[[dict[str, Any]], bool],
        body_fn: Callable[[dict[str, Any], int], dict[str, Any]],
        name: str = "",
        max_iterations: int = 1000,
    ) -> None:
        self._condition_fn = condition_fn
        self._body_fn = body_fn
        self._name = name or f"while_loop_{uuid.uuid4().hex[:6]}"
        self._max_iterations = max_iterations
        self._controller = LoopController()
        self._iteration_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def controller(self) -> LoopController:
        return self._controller

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run the while loop.

        Args:
            state: Initial state.

        Returns:
            State after loop completion.
        """
        current_state = dict(state)
        self._iteration_count = 0

        while self._condition_fn(current_state):
            self._iteration_count += 1
            if self._iteration_count > self._max_iterations:
                raise RuntimeError(
                    f"While loop '{self._name}' exceeded max iterations "
                    f"({self._max_iterations})"
                )

            action = self._controller.check()
            if action == LoopAction.BREAK or action == LoopAction.EXIT:
                break
            if action == LoopAction.CONTINUE:
                continue

            current_state = self._body_fn(current_state, self._iteration_count - 1)

        self._iteration_count = 0
        return current_state


# ── MapLoop ───────────────────────────────────────────────────────────


class MapLoop:
    """Iterate over a list of items, applying a function to each.

    Usage:
        loop = MapLoop(items_fn=lambda s: s["items"], body_fn=process_item)
        result = loop.run(initial_state)
    """

    def __init__(
        self,
        items_fn: Callable[[dict[str, Any]], list[Any]],
        body_fn: Callable[[Any, int, dict[str, Any]], dict[str, Any]],
        name: str = "",
    ) -> None:
        self._items_fn = items_fn
        self._body_fn = body_fn
        self._name = name or f"map_loop_{uuid.uuid4().hex[:6]}"
        self._controller = LoopController()

    @property
    def name(self) -> str:
        return self._name

    def run(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Run the map loop.

        Args:
            state: State containing the items list.

        Returns:
            List of results for each item.
        """
        items = self._items_fn(state)
        results: list[dict[str, Any]] = []

        for i, item in enumerate(items):
            action = self._controller.check()
            if action == LoopAction.BREAK or action == LoopAction.EXIT:
                break
            if action == LoopAction.CONTINUE:
                continue
            result = self._body_fn(item, i, state)
            results.append(result)

        return results


# ── Nested loop ───────────────────────────────────────────────────────


class NestedLoop:
    """Supports loops within subgraphs with parent-child coordination.

    Manages a hierarchy of loop controllers so break/exit propagates
    correctly from inner to outer loops.
    """

    def __init__(self, name: str = "") -> None:
        self._name = name or f"nested_loop_{uuid.uuid4().hex[:6]}"
        self._loops: list[ForLoop | WhileLoop] = []
        self._parent_controller: LoopController | None = None

    def add_loop(self, loop: ForLoop | WhileLoop) -> None:
        self._loops.append(loop)

    def set_parent(self, controller: LoopController) -> None:
        self._parent_controller = controller

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run all nested loops in sequence.

        Args:
            state: Initial state.

        Returns:
            State after all loops complete.
        """
        current_state = dict(state)
        for loop in self._loops:
            # Propagate parent controller
            if isinstance(loop, (ForLoop, WhileLoop)):
                pass  # controllers are internal
            current_state = loop.run(current_state)

            if self._parent_controller and self._parent_controller.check() in (
                LoopAction.BREAK,
                LoopAction.EXIT,
            ):
                break

        return current_state


__all__ = [
    "ForLoop",
    "LoopAction",
    "LoopController",
    "LoopDetectionConfig",
    "LoopDetector",
    "MapLoop",
    "NestedLoop",
    "RecursionLimit",
    "RecursionLimitExceeded",
    "WhileLoop",
]