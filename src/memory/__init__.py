"""Session + long-term memory for the vertex-agent backend.

- ``src.memory.checkpointer`` (Task 4): short-term session memory via a
  LangGraph checkpointer (``MemorySaver`` dev / ``PostgresSaver`` production).
- ``src.memory.cleanup`` (Task 4): stale-thread cleanup job / CLI.
- ``src.memory.store`` (Task 5): long-term memory Store factory (``InMemoryStore``
  dev / ``PostgresStore`` production, optional pgvector index).
- ``src.memory.memory_backend`` (Task 5): the agent filesystem backend that
  mounts ``/memory/`` on the Store — per-user namespaces via the Runtime
  context (``UserContext``), skills stay on disk.

``__init__`` stays import-free so ``python -m src.memory.cleanup`` does not
trigger a runpy "found in sys.modules" RuntimeWarning.
"""
