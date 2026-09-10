# Memory & Persistence

> **Nguồn tham khảo:** LangGraph `checkpoint/` (BaseCheckpointSaver, Checkpoint), `store/` (BaseStore); DeepAgents `backends/store.py`, `middleware/memory.py`, `middleware/summarization.py`; orchestrator MongoDB checkpointing + Store, memory files (AGENTS.md, MEMORY.md)

## Mục tiêu

Xây dựng memory và persistence system: session checkpointing, long-term memory, cross-session memory, và memory consolidation.

## Tasks

### Task 4.1: Checkpoint System (Short-term Memory)

**Mô tả:** Implement checkpoint system cho session memory: snapshot graph state sau mỗi step.

**File tham khảo:**
- LangGraph: `checkpoint/base/__init__.py` (BaseCheckpointSaver, Checkpoint, CheckpointMetadata, PendingWrite)
- `checkpoint/memory/` (InMemorySaver), `checkpoint/postgres/` (PostgresSaver)
- `pregel/_checkpoint.py`

**Yêu cầu:**
- BaseCheckpointSaver: `get`, `get_tuple`, `list`, `put`, `put_writes`
- Checkpoint schema: `v`, `id`, `ts`, `channel_values`, `channel_versions`, `versions_seen`
- Pending writes: crash recovery support
- InMemorySaver: cho dev/testing
- PostgresSaver: cho production
- Checkpoint metadata: `source`, `step`, `parents`, `run_id`
- Time travel: query old checkpoints, replay từ checkpoint

### Task 4.2: Long-term Memory Store

**Mô tả:** Implement long-term memory store: cross-session memory qua BaseStore.

**File tham khảo:**
- LangGraph: `store/base/__init__.py` (BaseStore, Item, SearchResult)
- DeepAgents: `backends/store.py` (StoreBackend)
- chatboth-orchestrator: MongoDBStore patterns

**Yêu cầu:**
- BaseStore interface: `put`, `get`, `search`, `delete`
- Item schema: `key`, `value`, `namespace`, `created_at`, `updated_at`
- Namespace-based isolation: per-user namespaces `("memories", user_id)`
- InMemoryStore: cho dev/testing
- PostgresStore: cho production (pgvector support)
- Semantic search: vector search trong store items
- Cross-session: memory tồn tại qua nhiều sessions

### Task 4.3: Memory Backend (Filesystem-as-Memory)

**Mô tả:** Implement memory backend: filesystem tools đọc/ghi vào Store-backed virtual filesystem.

**File tham khảo:**
- DeepAgents: `backends/store.py` (StoreBackend), `backends/composite.py` (CompositeBackend)
- Vertex-agent: `src/memory/memory_backend.py`

**Yêu cầu:**
- StoreBackend: backend cho Store-backed memory filesystem
- CompositeBackend: route `/memory/` -> StoreBackend, mọi path khác -> FilesystemBackend
- NamespaceFactory: `Callable[[Runtime], tuple[str, ...]]` -> per-user namespace
- UserContext: dataclass với user_id cho per-user isolation
- Virtual file `/memory/notes.md`: agent đọc/ghi long-term notes
- Memory guidance: system prompt hướng dẫn agent sử dụng long-term memory

### Task 4.4: AGENTS.md / Memory Files System

**Mô tả:** Implement memory files system: AGENTS.md, MEMORY.md, USER.md injection vào system prompt.

**File tham khảo:**
- DeepAgents: `middleware/memory.py` (MemoryMiddleware)
- orchestrator: memory files pattern (USER.md, MEMORY.md, IDENTITY.md, AGENTS.md)

**Yêu cầu:**
- MemoryMiddleware: load memory files từ backend paths
- Memory file types:
  - `AGENTS.md`: agent identity và instructions
  - `MEMORY.md`: conversation memory
  - `USER.md`: user profile và preferences
  - `IDENTITY.md`: agent identity
- Static injection: load vào system prompt mỗi turn
- Cache control: Anthropic prompt caching support
- HTML comments stripping: `<!-- -->` tự động xóa
- Progressive disclosure: chỉ load frontmatter trước, body khi cần

### Task 4.5: StoreBackend Namespace Management

**Mô tả:** Implement namespace management cho multi-tenant store isolation.

**File tham khảo:**
- DeepAgents: `backends/store.py` (StoreBackend, NamespaceFactory)
- LangGraph: `store/base/` namespace patterns
- LangGraph: `runtime.py` (Runtime context)

**Yêu cầu:**
- NamespaceFactory: factory function tạo namespace từ runtime context
- User-based isolation: `("memories", user_id)` namespace
- Bot/tenant-based: `("memories", bot_id, user_id)` namespace
- Global namespace: cho shared memory
- Namespace resolution: runtime -> context -> fallback
- Error handling: raise RuntimeError khi không có user context
- Access control: namespace-level permissions

### Task 4.6: Dreaming System (Background Self-Improvement)

**Mô tả:** Implement dreaming system: background self-improvement qua memory consolidation, thread scanning, và knowledge synthesis.

**File tham khảo:**
- Vertex-agent: `src/memory/dreaming/` (enqueue, scan, dream, consolidate, loader)
- LangMem: `reflection.py` patterns
- LangGraph: store + checkpoint query APIs

**Yêu cầu:**
- **EnqueueAfterTurnMiddleware**: end-of-turn hook để enqueue thread for dreaming
- **ScanSystem**: scan thread IDs từ checkpoint để tìm threads cần dream
- **Dream Engine**: synthesize conversation thành facts, lessons, conflict markers
- **Consolidation**: merge dream results vào long-term store
- **Alert System**: heartbeat freshness + backlog monitoring
- Store items for dreams: `memories/` (facts), `system.lessons/` (lessons), `system.conflict_markers/` (conflicts)
- Staleness detection: item không đọc trong N ngày
- Testable: deterministic consolidation test qua Postgres raw SQL