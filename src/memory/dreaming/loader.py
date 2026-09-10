"""Thread-history loading for the dreaming graph (Phase 6).

Reconstructs a thread's full message history from checkpoints using
the ``BaseCheckpointSaver`` API.

There are two strategies:
1. **State-based** (preferred) — if a ``get_state`` callable is provided,
   resolves the full message list through the agent's state API (supports
   newer deepagents versions where messages live in reducers across pending
   writes).
2. **Checkpoint-walk** — walks all checkpoint tuples via ``list()``
   collecting messages from ``__start__`` / ``messages`` channels,
   deduplicating by id or content hash.

Strategy 2 is used as fallback when no ``get_state`` is available.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

_MESSAGE_ROLE_MAP: dict[str, type[BaseMessage]] = {
    "human": HumanMessage,
    "user": HumanMessage,
    "ai": AIMessage,
    "assistant": AIMessage,
}


def _to_base_message(item: Any) -> BaseMessage | None:
    """Convert a dict or BaseMessage to a BaseMessage instance."""
    if isinstance(item, BaseMessage):
        return item
    if isinstance(item, dict):
        role = item.get("role", "user")
        content = item.get("content", "")
        msg_cls = _MESSAGE_ROLE_MAP.get(role, HumanMessage)
        msg_id = item.get("id")
        try:
            return msg_cls(content=content, id=msg_id) if msg_id else msg_cls(content=content)
        except Exception:
            return msg_cls(content=content)
    return None


def _extract_messages_from_channel_value(value: Any) -> list[BaseMessage]:
    """Try to extract BaseMessages from an arbitrary checkpoint channel value."""
    if isinstance(value, list):
        result = []
        for item in value:
            msg = _to_base_message(item)
            if msg is not None:
                result.append(msg)
        return result
    if isinstance(value, dict):
        msgs = value.get("messages", [])
        if msgs and isinstance(msgs, (list, tuple)):
            return _extract_messages_from_channel_value(msgs)
    return []


def load_thread_messages(
    checkpointer: BaseCheckpointSaver,
    thread_id: str,
    *,
    max_messages: int | None = None,
    get_state: Callable[[dict], Any] | None = None,
) -> list[BaseMessage]:
    """Reconstruct the full ordered message list for a thread.

    Args:
        checkpointer: The checkpointer the main graph persisted into (same
            instance / database).
        thread_id: The thread whose messages to read.
        max_messages: Optional tail-window cap — keep only the last N messages.
        get_state: Optional ``agent.get_state(config)`` callable. When provided,
            the full message list is resolved through the agent's state API,
            which handles reducers and pending writes correctly.

    Returns:
        The reconstructed list of ``BaseMessage`` in chronological order, or
        ``[]`` when the thread has no checkpoints.
    """
    # Strategy 1: state-based (handles deepagents reducers correctly)
    if get_state is not None:
        try:
            state = get_state({"configurable": {"thread_id": thread_id}})
            if state is not None:
                messages = list(state.values.get("messages", []))
                if max_messages is not None and len(messages) > max_messages:
                    messages = messages[-max_messages:]
                return messages
        except Exception:
            pass

    # Strategy 2: walk all checkpoints
    seen_ids: set[str] = set()
    messages: list[BaseMessage] = []

    for tup in checkpointer.list({"configurable": {"thread_id": thread_id}}):
        ck = tup.checkpoint
        if isinstance(ck, dict):
            channel_values = ck.get("channel_values", {})
        else:
            channel_values = getattr(ck, "channel_values", {})

        for key, value in channel_values.items():
            # Skip non-message channels
            if key in ("skills_metadata", "pending_sends"):
                continue
            extracted = _extract_messages_from_channel_value(value)
            for msg in extracted:
                msg_content = getattr(msg, "content", "") or ""
                if not msg_content and not isinstance(msg, (HumanMessage, AIMessage)):
                    continue
                if not msg_content:
                    continue
                msg_id = getattr(msg, "id", None) or getattr(msg, "id_", None)
                dedup_key = msg_id or msg_content
                if dedup_key not in seen_ids:
                    seen_ids.add(dedup_key)
                    messages.append(msg)

    messages.reverse()
    if max_messages is not None and len(messages) > max_messages:
        messages = messages[-max_messages:]

    return messages


def scan_thread_ids(
    checkpointer: BaseCheckpointSaver,
    *,
    root_namespace: str = "",
) -> list[str]:
    """Enumerate distinct top-level ``thread_id``s recorded in a checkpointer.

    Args:
        checkpointer: Any ``BaseCheckpointSaver`` instance.
        root_namespace: Only threads whose ``checkpoint_ns`` equals this value
            are returned (default ``""`` = top-level agent threads).

    Returns:
        Deduplicated, lexicographically sorted list of thread ids.
    """
    threads: set[str] = set()
    # Pass None to list all checkpoints, then filter by thread_id
    for tup in checkpointer.list(None):
        cfg = tup.config.get("configurable", {})
        if cfg.get("checkpoint_ns", "") != root_namespace:
            continue
        tid = cfg.get("thread_id", "")
        if tid:
            threads.add(str(tid))
    return sorted(threads)


__all__ = ["load_thread_messages", "scan_thread_ids"]