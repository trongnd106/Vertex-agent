# Backend & Storage

> **Nguồn tham khảo:** DeepAgents `backends/` (protocol.py, state.py, filesystem.py, store.py, composite.py, sandbox.py, local_shell.py); LangGraph `store/` (BaseStore), `checkpoint/` (BaseCheckpointSaver); orchestrator session state backends (Redis, HTTP, InMem)

## Mục tiêu

Xây dựng backend infrastructure: pluggable storage backends, session state, configuration management, và database setup.

## Tasks

### Task 8.1: Backend Protocol & Implementations

**Mô tả:** Implement BackendProtocol và các implementations.

**File tham khảo:**
- DeepAgents: `backends/protocol.py` (BackendProtocol, SandboxBackendProtocol, data types)
- `backends/state.py` (StateBackend)
- `backends/filesystem.py` (FilesystemBackend)
- `backends/composite.py` (CompositeBackend)

**Yêu cầu:**
- BackendProtocol interface:
  - `ls`, `read`, `write`, `edit`, `delete`, `glob`, `grep`
  - `download_files`, `upload_files`
  - async versions: `als`, `aread`, `awrite`, ...
- StateBackend: in-memory, checkpointed, không persistent cross-thread
- FilesystemBackend: disk operations với root_dir
- CompositeBackend: route-based multiplexing với `(default, routes)`
- SandboxBackendProtocol: thêm `execute`, `aexecute`
- BaseSandbox ABC: `execute`, `upload_files`, `download_files`, `id`
- LocalShellBackend: FilesystemBackend + local shell (dev only)
- LangSmithSandbox: remote sandbox

### Task 8.2: Session State Management

**Mô tả:** Implement session state quản lý: lưu trữ state per session.

**File tham khảo:**
- orchestrator: `session_state_*.py` (SessionStateInMem, SessionStateRedis, SessionStateHTTP)
- `task_engine.py` variable management (plan/bot/sys scopes)

**Yêu cầu:**
- Session state interface:
  - `store_variable(scope, session_id, plan_id, bot_id, name, value, type)`
  - `get_variable(execution, name) -> value`
- Implementations:
  - **InMemoryBackend**: dict-based, testing
  - **RedisBackend**: Redis, production (với connection pool)
  - **DatabaseBackend**: SQL/Postgres, persistent
- Variable scopes:
  - `plan`: trong execution của một plan
  - `bot`: cross-session của một bot
  - `sys`: system global
- JSON schema auto-detection cho variable types
- Consistent hashing cho Redis scale ngang

### Task 8.3: Configuration Management

**Mô tả:** Xây dựng configuration management system.

**File tham khảo:**
- Vertex-agent: `src/config/__init__.py`, `pyproject.toml`, `langgraph.json`
- orchestrator: `config.py`
- DeepAgents: profiles system

**Yêu cầu:**
- Configuration layers: default -> env -> file -> runtime
- Config file formats: YAML, JSON, TOML, .env
- Environment variable resolution: `AGENT_MODEL`, `DATABASE_URL`, etc.
- Provider configuration: API keys, endpoints, model names
- Agent configuration: middleware list, tool permissions, profiles
- Deployment configuration: server, database, scaling
- Configuration validation: schema validation, required fields
- Configuration reload: hot reload without restart

### Task 8.4: Database Infrastructure

**Mô tả:** Setup database infrastructure: Postgres, pgvector, connection management.

**File tham khảo:**
- Vertex-agent: `infra/docker-compose.yml` (Postgres + Redis)
- LangGraph: checkpoint-postgres, store-postgres
- Vertex-agent: `src/memory/checkpointer.py`

**Yêu cầu:**
- Postgres setup: docker-compose, connection pool
- pgvector extension: cho vector search trong store
- Migration management: schema creation, migration scripts
- Connection pooling: asyncpg connection pool
- Checkpointer tables: checkpoint, checkpoint_blob, checkpoint_writes, checkpoint_mappings
- Store tables: store + store_blob
- Redis setup: optional, cho session state và caching
- Database health check: connection monitoring
- Backup/restore: database backup strategy

### Task 8.5: LocalShellBackend & Sandbox Integration

**Mô tả:** Implement LocalShellBackend và integration với sandbox systems.

**File tham khảo:**
- DeepAgents: `backends/local_shell.py` (LocalShellBackend, DEFAULT_EXECUTE_TIMEOUT)
- `backends/sandbox.py` (BaseSandbox)
- Vertex-agent: `src/agent/tools/sandbox.py`

**Yêu cầu:**
- LocalShellBackend:
  - Kế thừa FilesystemBackend
  - Thêm `execute` method (shell command)
  - Security warning: dev only, không sandbox
  - Timeout: DEFAULT_EXECUTE_TIMEOUT
  - Permission check: cần interrupt_on hoặc HITL
- Custom sandbox từ BaseSandbox:
  - Execute trong container
  - File upload/download
  - Resource limits
- Dev vs Production detection:
  - Dev: LocalShellBackend
  - Production: container sandbox hoặc LangSmith sandbox
- Role-based sandbox selection: customer-support vs operator