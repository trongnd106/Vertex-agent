"""Reducer functions for channel-based state management.

Reducers define how multiple updates to the same state field are merged.
They are used with ``BinaryOperatorAggregate`` channels and with
``Annotated[type, reducer]`` type annotations in state schemas.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage


def add_messages(
    left: list[BaseMessage],
    right: list[BaseMessage] | BaseMessage,
) -> list[BaseMessage]:
    """Merge two message lists by message ID.

    Messages with the same ID are overwritten (last wins). This mirrors
    LangGraph's ``add_messages`` reducer used in ``Annotated[list, add_messages]``.

    Args:
        left: Existing message list.
        right: New message(s) to merge.

    Returns:
        Merged message list.
    """
    if not isinstance(right, list):
        right = [right]

    seen: dict[str, int] = {}
    merged: list[BaseMessage] = []

    for msg in left:
        mid = getattr(msg, "id", None) or getattr(msg, "id_", None) or id(msg)
        key = str(mid)
        if key in seen:
            merged[seen[key]] = msg
        else:
            seen[key] = len(merged)
            merged.append(msg)

    for msg in right:
        mid = getattr(msg, "id", None) or getattr(msg, "id_", None) or id(msg)
        key = str(mid)
        if key in seen:
            merged[seen[key]] = msg
        else:
            seen[key] = len(merged)
            merged.append(msg)

    return merged


def concat(left: list[Any], right: list[Any] | Any) -> list[Any]:
    """Concatenate two lists (or append a single item).

    Args:
        left: Existing list.
        right: New item(s) to append.

    Returns:
        Concatenated list.
    """
    if not isinstance(right, list):
        right = [right]
    return left + right


__all__ = ["add_messages", "concat"]