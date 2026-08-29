"""Thread-history loading for the dreaming graph (Phase 6).

The dream graph reads a thread's full message history back out of the
checkpointer. A naive ``checkpointer.get_tuple(...).checkpoint["channel_values"]
["messages"]`` does NOT work because deepagents stores ``messages`` on a
``DeltaChannel`` (`deepagents/graph.py:73`:
``Annotated[list[AnyMessage], DeltaChannel(_messages_delta_reducer,
snapshot_frequency=50)]``) — for non-snapshot steps the channel is absent from
``channel_values`` (live-probed: the tuple's ``channel_values`` held only
``skills_metadata``).

Reconstruction therefore mirrors what LangGraph's own ``Pregel.get_state``
does internally (``langgraph/pregel/main.py::_prepare_state_snapshot`` →
``langgraph/pregel/_checkpoint.py::channels_from_checkpoint``): an ancestor
walk via ``BaseCheckpointSaver.get_delta_channel_history``
(``langgraph/checkpoint/base/__init__.py:582``) accumulating per-channel
deltas up to the nearest ``_DeltaSnapshot`` seed, replayed with the *exact*
reducer the main graph uses (``_messages_delta_reducer``). Verified to
reproduce `agent.get_state(config).values["messages"]` byte-for-byte, on both
``MemorySaver`` and ``PostgresSaver``.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.channels.delta import DeltaChannel
from langgraph.pregel._checkpoint import channels_from_checkpoint

from deepagents._messages_reducer import _messages_delta_reducer

#: The DeltaChannel spec deepagents applies to the messages channel
#: (`deepagents/graph.py:73`). Kept in lock-step with the main graph so any
#: thread written by it reconstructs identically here.
MESSAGES_CHANNEL = "messages"
MESSAGES_DELTA_SPEC = DeltaChannel(_messages_delta_reducer, snapshot_frequency=50)


def load_thread_messages(
    checkpointer: BaseCheckpointSaver,
    thread_id: str,
    *,
    max_messages: int | None = None,
) -> list[BaseMessage]:
    """Reconstruct the full ordered message list for a thread.

    Args:
        checkpointer: The checkpointer the main graph persisted into (same
            instance / database).
        thread_id: The thread whose messages to read.
        max_messages: Optional tail-window cap — keep only the last N messages.

    Returns:
        The reconstructed list of ``BaseMessage`` in chronological order, or
        ``[]`` when the thread has no checkpoints.
    """
    tup = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
    if tup is None:
        return []
    channels, _ = channels_from_checkpoint(
        {MESSAGES_CHANNEL: MESSAGES_DELTA_SPEC},
        tup.checkpoint,
        saver=checkpointer,
        config=tup.config,
    )
    messages = list(channels[MESSAGES_CHANNEL].value or [])
    if max_messages is not None and len(messages) > max_messages:
        messages = messages[-max_messages:]
    return messages


def scan_thread_ids(
    checkpointer: BaseCheckpointSaver,
    *,
    root_namespace: str = "",
) -> list[str]:
    """Enumerate distinct top-level ``thread_id``s recorded in a checkpointer.

    Used by the cold-thread scan entrypoint (`python -m src.memory.dreaming.scan`).

    Args:
        checkpointer: Any ``BaseCheckpointSaver`` (``MemorySaver`` or
            ``PostgresSaver`` — both verified to support
            ``checkpointer.list(None)``).
        root_namespace: Only threads whose ``checkpoint_ns`` equals this value
            are returned (default ``""`` = top-level agent threads, excluding
            subagent namespaces).

    Returns:
        Deduplicated, lexicographically sorted list of thread ids.
    """
    threads: set[str] = set()
    for tup in checkpointer.list(None):
        cfg = tup.config["configurable"]
        if cfg.get("checkpoint_ns", "") == root_namespace:
            threads.add(str(cfg["thread_id"]))
    return sorted(threads)


__all__ = ["load_thread_messages", "scan_thread_ids"]