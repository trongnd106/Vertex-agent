"""Channel-based state management for the agent graph.

Implements LangGraph-inspired channel types that govern how individual state
fields behave under updates — overwrite, accumulate, reduce, or ephemeral.
Each channel is an instance of ``BaseChannel`` (defined in
:mod:`src.graph.types`).

Channel types
=============

- ``LastValue`` — stores only the last value (default; overwrite semantics).
- ``BinaryOperatorAggregate`` — applies a reducer function (e.g. ``operator.add``).
- ``Topic`` — accumulates multiple values (PubSub-style; supports dedup).
- ``EphemeralValue`` — exists for one step only, not persisted.
- ``NamedBarrierValue`` — synchronisation barrier (waits for N writers).

Version tracking
================

Every channel maintains a monotonically-increasing *version* counter.
After each step the runtime compares pre- and post-step versions to
decide which nodes to schedule next — a channel whose version changed
triggers any node subscribed to it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Generic, Hashable, TypeVar, Annotated, ForwardRef, get_origin, get_args

from src.graph.types import BaseChannel

T = TypeVar("T")
U = TypeVar("U")


# ──────────────────────────────────────────────────────────────────────
# LastValue
# ──────────────────────────────────────────────────────────────────────


class LastValue(BaseChannel[T, U]):
    """Stores only the last value written to it (overwrite semantics).

    Accepts at most one update per step. This is the *default* channel
    behaviour — most scalar state fields (``int``, ``str``, ``dict``) use
    this.

    State transitions::

        initial: None
        update("a") → "a"
        update("b") → "b"   # overwrites
    """

    def __init__(self, initial: T | None = None) -> None:
        self._value: T | None = initial
        self._initial: T | None = initial
        self._updated: bool = False
        self._version: int = 0

    @property
    def value(self) -> T | None:
        return self._value

    def update(self, values: Sequence[U]) -> bool:
        if len(values) > 1:
            msg = f"LastValue accepts at most 1 update per step, got {len(values)}"
            raise ValueError(msg)
        if not values:
            return False
        new = values[0]
        if self._value == new:
            return False
        self._value = new
        self._updated = True
        self._version += 1
        return True

    def checkpoint(self) -> T | None:
        return self._value

    def from_checkpoint(self, checkpoint: T | None) -> None:
        self._value = checkpoint
        self._updated = False
        self._version += 1

    def reset(self) -> None:
        self._value = self._initial
        self._updated = False

    @property
    def version(self) -> int:
        return self._version

    @property
    def updated(self) -> bool:
        return self._updated


# ──────────────────────────────────────────────────────────────────────
# BinaryOperatorAggregate
# ──────────────────────────────────────────────────────────────────────


class BinaryOperatorAggregate(BaseChannel[T, U]):
    """Applies a binary reducer function to accumulate values.

    Each update is combined with the current value via the reducer::

        current = reducer(current, update)

    Commonly used with ``operator.add`` for counters, or custom reducers
    for merging dicts.

    State transitions::

        initial: 0
        update([1]) → 0 + 1 = 1
        update([2]) → 1 + 2 = 3
    """

    def __init__(self, reducer: Callable[[T, U], T], initial: T | None = None) -> None:
        self._reducer = reducer
        self._value: T | None = initial
        self._initial: T | None = initial
        self._version: int = 0

    @property
    def value(self) -> T | None:
        return self._value

    def update(self, values: Sequence[U]) -> bool:
        if not values:
            return False
        for v in values:
            if self._value is None:
                self._value = v  # type: ignore[assignment]
            else:
                self._value = self._reducer(self._value, v)
        self._version += 1
        return True

    def checkpoint(self) -> T | None:
        return self._value

    def from_checkpoint(self, checkpoint: T | None) -> None:
        self._value = checkpoint
        self._version += 1

    def reset(self) -> None:
        self._value = self._initial


# ──────────────────────────────────────────────────────────────────────
# Topic (PubSub)
# ──────────────────────────────────────────────────────────────────────


class Topic(BaseChannel[list[T], T]):
    """Accumulates multiple values in sequence (PubSub-style).

    Unlike ``LastValue``, ``Topic`` accepts *multiple* updates per step and
    appends them all. Supports optional deduplication via a ``unique_by``
    key-extractor function.

    State transitions::

        initial: []
        update(["a"]) → ["a"]
        update(["b", "c"]) → ["a", "b", "c"]   # append
    """

    def __init__(
        self,
        unique_by: Callable[[T], Hashable] | None = None,
        initial: list[T] | None = None,
    ) -> None:
        self._values: list[T] = list(initial) if initial is not None else []
        self._unique_by = unique_by
        self._version: int = 0

    @property
    def value(self) -> list[T]:
        return list(self._values)

    def update(self, values: Sequence[list[T] | T]) -> bool:
        """Flatten updates and append unique items."""
        if not values:
            return False
        changed = False
        seen = set()
        if self._unique_by:
            seen.update(self._unique_by(v) for v in self._values)
        for item in values:
            if isinstance(item, list):
                for sub in item:
                    if self._unique_by:
                        key = self._unique_by(sub)
                        if key in seen:
                            continue
                        seen.add(key)
                    self._values.append(sub)
                    changed = True
            else:
                if self._unique_by:
                    key = self._unique_by(item)
                    if key in seen:
                        continue
                    seen.add(key)
                self._values.append(item)
                changed = True
        if changed:
            self._version += 1
        return changed

    def checkpoint(self) -> list[T]:
        return list(self._values)

    def from_checkpoint(self, checkpoint: list[T]) -> None:
        self._values = list(checkpoint)
        self._version += 1

    def reset(self) -> None:
        self._values.clear()


# ──────────────────────────────────────────────────────────────────────
# EphemeralValue
# ──────────────────────────────────────────────────────────────────────


class EphemeralValue(BaseChannel[T, U]):
    """Exists for one step only; *not* persisted in checkpoints.

    Useful for intermediate computation results that should not survive
    across graph steps.
    """

    def __init__(self) -> None:
        self._value: T | None = None
        self._version: int = 0

    @property
    def value(self) -> T | None:
        return self._value

    def update(self, values: Sequence[U]) -> bool:
        if not values:
            return False
        self._value = values[-1]  # type: ignore[assignment]
        self._version += 1
        return True

    def checkpoint(self) -> None:
        return None  # ephemeral: never persisted

    def from_checkpoint(self, checkpoint: None) -> None:
        self._value = None
        self._version += 1

    def reset(self) -> None:
        self._value = None


# ──────────────────────────────────────────────────────────────────────
# NamedBarrierValue
# ──────────────────────────────────────────────────────────────────────


class NamedBarrierValue(BaseChannel[bool, str]):
    """Synchronisation barrier: waits for *N* named writers before unblocking.

    Each update supplies a writer *name*; once all expected names have
    checked in, the channel's value becomes ``True`` and triggers any
    subscribed nodes.
    """

    def __init__(self, expected_writers: set[str]) -> None:
        self._expected = set(expected_writers)
        self._received: set[str] = set()
        self._version: int = 0

    @property
    def value(self) -> bool:
        return self._received >= self._expected

    def update(self, values: Sequence[str]) -> bool:
        for name in values:
            self._received.add(name)
        changed = self._received >= self._expected
        if changed:
            self._version += 1
        return changed

    def checkpoint(self) -> set[str]:
        return set(self._received)

    def from_checkpoint(self, checkpoint: set[str]) -> None:
        self._received = set(checkpoint)
        self._version += 1

    def reset(self) -> None:
        self._received.clear()


# ──────────────────────────────────────────────────────────────────────
# Channel factory
# ──────────────────────────────────────────────────────────────────────


def _resolve_annotation(annotation: Any) -> Any:
    """Resolve a ForwardRef annotation by evaluating it.

    With ``from __future__ import annotations``, all annotations are
    ``ForwardRef`` strings at runtime. This function resolves them
    against available builtins and typing constructs.
    """
    if isinstance(annotation, ForwardRef):
        try:
            return eval(annotation.__forward_arg__)
        except NameError:
            pass
    return annotation


def channel_for_field(
    annotation: Any,
    field_name: str = "",
) -> BaseChannel[Any, Any]:
    """Create the appropriate channel for a state schema field annotation.

    Inspects the type annotation (including ``Annotated`` metadata) and
    returns the correct channel type:

    - ``Annotated[list, add_messages]`` → ``Topic(unique_by=id)``
    - ``Annotated[T, operator.add]`` → ``BinaryOperatorAggregate(operator.add)``
    - ``Annotated[T, reducer_fn]`` → ``BinaryOperatorAggregate(reducer_fn)``
    - plain types → ``LastValue``

    Args:
        annotation: The field annotation from the state schema.
        field_name: The field name (for error messages).

    Returns:
        A configured ``BaseChannel`` instance.
    """
    annotation = _resolve_annotation(annotation)

    origin = get_origin(annotation)
    args = list(get_args(annotation))

    if origin is not None and origin is list:
        return Topic()

    # Handle Annotated[type, reducer]
    if origin is Annotated:
        base_type, *meta = args
        if meta:
            reducer = meta[0]
            # Check for add_messages first (special: returns Topic, not BinaryOperatorAggregate)
            reducer_name = getattr(reducer, "__name__", None)
            if reducer_name == "add_messages":
                # Use the message id for deduplication
                return Topic(unique_by=lambda msg: str(getattr(msg, "id", id(msg))))
            if callable(reducer):
                return BinaryOperatorAggregate(reducer=reducer)

    # Handle operator.add and similar
    if callable(annotation) and hasattr(annotation, "__name__"):
        name = annotation.__name__
        if name in ("add", "concat"):
            return BinaryOperatorAggregate(reducer=annotation)

    # Handle plain `list` type
    if annotation is list:
        return Topic()

    # Default for annotated types with known reducers
    if origin is Annotated and args:
        return LastValue()

    # Default: LastValue
    return LastValue()


__all__ = [
    "BinaryOperatorAggregate",
    "EphemeralValue",
    "LastValue",
    "NamedBarrierValue",
    "Topic",
    "channel_for_field",
]