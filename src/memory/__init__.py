"""Session (short-term) memory via LangGraph checkpointers.

Phase 4: a checkpointer auto-persists the full graph state per ``thread_id``;
resuming a session is just invoking with the same ``thread_id``. See
``src.memory.checkpointer`` (the factory) and ``src.memory.cleanup`` (the
stale-thread cleanup job / CLI).

``__init__`` stays import-free so ``python -m src.memory.cleanup`` does not
trigger a runpy "found in sys.modules" RuntimeWarning.
"""
