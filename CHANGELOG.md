# Changelog - Vertex Agent

> **Project:** DeepAgents Vertex Agent — Backend agent built on LangGraph + DeepAgents
> **Created:** 2026-09-08

---

## [0.5.0] — 2026-09-09

### Task 10: Advanced Features ✅

Built advanced features including a fully-functional dreaming self-improvement system, rubric-based self-evaluation middleware, a multi-step deep research agent, multi-modal support (images, video, code execution), plugin/hook extension systems, knowledge base RAG integration, and model routing/fallback.

| Subtask | Description | Status |
|---------|-------------|--------|
| 10.1 | **Dreaming Enqueue & Scan** — `EnqueueAfterTurnMiddleware` using deepagents' `aafter_agent`/`after_agent` hooks with thread_id/user_id extraction from `runtime.execution_info`/`runtime.context`. Thread discovery via `saver.list(None)`. In-memory queue and background processing. Configurable per-session enable/disable. Queue types support (in-memory, database). | ✅ |
| 10.2 | **Dreaming Dream & Consolidation** — `load_thread_messages()` with state-based (via optional `get_state` callable) and checkpoint-walk fallback strategies. Dict-to-BaseMessage conversion. Structured dream extraction: facts (`memories/`), lessons (`system.lessons/`), conflicts (`system.conflict_markers/`). Staleness detection, priority-based aging, conflict resolution, deduplication, batch processing. | ✅ |
| 10.3 | **Rubric & Self-Evaluation** — `RubricMiddleware` with 3-tier criteria (identity/critical/simple). `CriterionEval`, `CriterionPass`, `CriterionFail` data models. Grader sub-agent for structured scoring (`GraderResponse`). Revision loop with configurable max retries and feedback injection as `HumanMessage`. Rubric profiles for reusable configs. Streaming-compatible evaluation. | ✅ |
| 10.4 | **Deep Research Agent** — Multi-step research workflow: planning (LLM or heuristic query generation) → parallel search (pluggable providers: Tavily, DuckDuckGo, Placeholder) → deep document reading with LLM analysis → cross-referencing (agreement/disagreement detection) → synthesis (cited answer generation) → iterative refinement (deep mode only). `ProgressCallback` streaming. `ResearchDepth` enum (QUICK/STANDARD/DEEP). `Searcher`, `DocumentReader`, `Synthesizer` components. `run_research()` convenience function. 51 tests. | ✅ |
| 10.5 | **Multi-Modal & Extensions** — `ImageProcessor` (base64 encode/decode, format detection, message extraction). `VideoFrameExtractor` (ffmpeg-based frame extraction, scene detection, histogram dedup). `CodeExecutor` (sandboxed Python exec with safe builtins/modules, stdout/stderr capture, plot capture). `PluginRegistry` (lifecycle management, hook registration, dynamic module loading, directory discovery, custom tool/middleware/model registration). `HookRegistry` (typed lifecycle events, priority ordering, one-shot hooks, async/sync emit). `RAGEngine` (chunking, embedding, vector search over `InMemoryVectorStore`, LLM synthesis). `ModelRouter` (task-type routing, cost-aware selection, fallback chains, `invoke_with_fallback()`). 91 tests. | ✅ |

**Key implementation details:**
- `EnqueueAfterTurnMiddleware` inherits from deepagents' `AgentMiddleware` (not our custom `src.middleware.types.AgentMiddleware`) to satisfy factory checks for `trace_policy`, `wrap_tool_call`, `awrap_tool_call` attributes
- `load_thread_messages()` walks all checkpoints via `saver.list(None)`, extracts from all channels (skipping `skills_metadata`/`pending_sends`), converts dict messages to `HumanMessage`/`AIMessage`, deduplicates by id/content
- `RubricMiddleware` returns `[]` from a `tools` property to avoid breaking deepagents factory's `getattr(m, "tools", [])` check
- Research `Searcher` deduplicates across providers by URL; `DocumentReader` falls back to extractive summarization when LLM unavailable; `Synthesizer` uses simple concatenation fallback
- `CodeExecutor` wraps `__import__` to restrict imports to an allowlist (`SAFE_MODULE_NAMES`); removes `exec`/`eval`/`compile`/`open`/`input` from sandbox builtins
- `PluginRegistry.load_from_directory()` discovers `*_plugin.py` modules automatically
- `ModelRouter.invoke_with_fallback()` tries models in priority order; raises `RuntimeError` only when all models fail
- `InMemoryVectorStore` uses cosine similarity; `RAGEngine._keyword_search()` provides embedding-free fallback

**New files:**
- `src/research/__init__.py`, `models.py`, `searcher.py`, `reader.py`, `synthesizer.py`, `agent.py` — Deep Research Agent (6 files)
- `src/multimodal/__init__.py`, `image.py`, `video.py`, `code_execution.py` — Multi-Modal support (4 files)
- `src/extensions/__init__.py`, `plugin.py`, `hooks.py` — Plugin/Hook extension system (3 files)
- `src/knowledge/__init__.py`, `rag.py`, `vector_store.py` — Knowledge Base RAG (3 files)
- `src/routing/models.py` — Model routing/fallback (1 file)

**Tests:** `test_research.py` (51), `test_multimodal.py` (43), `test_extensions.py` (31), `test_knowledge.py` (17), `test_routing.py` (+18 model routing tests) — 160 new test cases

---

## [0.4.1] — 2026-09-09

### Task 9: Deployment & Operations ✅

Built a production-ready deployment layer with LangGraph API server configuration, Docker containerization, FastAPI HTTP/SSE endpoints, rate limiting, request authentication, CORS support, infrastructure automation, and comprehensive operations documentation.

| Subtask | Description | Status |
|---------|-------------|--------|
| 9.1 | **LangGraph Server Setup** — Updated `langgraph.json` with Postgres checkpointer, store config (OpenAI embedding, 1536 dims, indexed `[text]` field), and environment variables. Created `config/dev.yml`, `config/staging.yml`, `config/production.yml` with environment-specific settings for agent model, database, deployment, and logging. | ✅ |
| 9.2 | **Docker & Containerization** — Multi-stage `Dockerfile` (builder stage copies pyproject.toml + installs deps; runtime stage copies source + config, cleans build tools). `infra/docker-compose.yml` with 3 services: postgres (pgvector/pg16, 512M/1CPU), redis (7-alpine, 256M, production profile only), agent (FastAPI, healthcheck, 2G/2CPU, production profile). Resource limits, healthchecks, and dependency ordering throughout. | ✅ |
| 9.3 | **API Layer & Gateway** — FastAPI server with endpoints: `POST /invoke` (sync agent invocation), `POST /stream` (SSE streaming), `GET /state/{thread_id}` / `POST /state/{thread_id}` (state management), `GET /health`, `GET /metrics`. Token-bucket `RateLimiter` (60 burst, 1/s sustained). Middleware chain: request ID + timing headers, API key auth (via `AUTH_TOKEN` env var), CORS (configurable origins). Standardized `ErrorResponse` schema. Auto-generated `/docs` (OpenAPI/Swagger) + `/redoc`. | ✅ |
| 9.4 | **Load Testing & Benchmarking** — Concurrent request safety verified (thread pool tests). p50/p95/p99 latency tracking infrastructure. `RateLimiter` concurrent safety validated with 10-thread hammer test. Rate limit integration tested end-to-end via FastAPI TestClient. | ✅ |
| 9.5 | **Operations Runbook** — 6 comprehensive guides: [Deployment Guide](docs/ops/deployment.md) (prerequisites, quick start, production deployment, env var reference), [Monitoring Guide](docs/ops/monitoring.md) (endpoints, logging, Docker logs, Prometheus scraping, alerting rules), [Troubleshooting Guide](docs/ops/troubleshooting.md) (5 common issues with diagnosis and fix, debugging checklist), [Backup & Restore](docs/ops/backup-restore.md) (manual/Docker/Docker volume backup, automated backup strategy, Redis persistence), [Scaling Guide](docs/ops/scaling.md) (horizontal scaling, nginx reverse proxy, resource sizing, database scaling, rate limiting), [Security Guide](docs/ops/security.md) (API key auth, CORS, sandbox security, database connection security, Docker secrets). | ✅ |

**Key implementation details:**
- `RateLimiter` uses injectable `time_function` for testability; thread-safe via `threading.Lock`
- FastAPI app factory pattern (`create_app()`) enables TestClient injection without env side-effects
- Auth middleware skips `/health` for public health check access; all other routes require `AUTH_TOKEN` when set
- SSE streaming uses `StreamingResponse` with `X-Accel-Buffering: no` for nginx compatibility
- `ErrorResponse` model provides standardized `error`, `detail`, `error_id` fields across all endpoints
- `lifespan` handler lazy-imports the agent graph so the server boots even without LLM keys
- Rate limit works per-user via `user_id` field; token-bucket refills continuously at configurable rate

**New files:**
- `src/api/__init__.py` — Package public API
- `src/api/server.py` — `create_app()`, `app`, `server_state`, endpoints, middleware
- `src/api/rate_limit.py` — `RateLimiter` token-bucket implementation
- `docs/ops/deployment.md` — Deployment guide
- `docs/ops/monitoring.md` — Monitoring guide
- `docs/ops/troubleshooting.md` — Troubleshooting guide
- `docs/ops/backup-restore.md` — Backup & restore guide
- `docs/ops/scaling.md` — Scaling guide
- `docs/ops/security.md` — Security guide

**Tests:** `test_api.py` — 27 test cases covering all 5 subtasks

---

## [0.4.0] — 2026-09-09

### Task 8: Backend Infrastructure ✅

Built a pluggable backend infrastructure layer with filesystem-like protocol implementations, session state management across memory/Redis/Postgres, layered configuration management with hot reload, database schema management with migration tracking, and sandboxed execution environments.

| Subtask | Description | Status |
|---------|-------------|--------|
| 8.1 | **Backend Protocol & Implementations** — `BackendProtocol` ABC with 10 operations (ls, read, write, edit, delete, glob, grep, download_files, upload_files + async counterparts via `als`/`aread`/`awrite`/etc.). `StateBackend` in-memory dict-based with checkpoint/rollback for testing. `FilesystemBackend` disk-backed with root directory isolation and path traversal protection. `CompositeBackend` route-based multiplexing with fnmatch pattern routing and `add_route()`/`remove_route()` lifecycle. `SandboxBackendProtocol` extends with `execute`/`aexecute`. `BaseSandbox` ABC for containerised execution. `FileInfo` dataclass with name, path, size, modified, is_dir, permissions, and `modified_iso` property. | ✅ |
| 8.2 | **Session State Management** — `SessionStateBackend` ABC with `store_variable()`/`get_variable()`/`list_variables()`/`delete_variable()`. `VariableScope` enum (PLAN/BOT/SYS). `SessionVariable` dataclass with auto type detection (string/integer/boolean/number/array/object/null). `InMemorySessionBackend` dict-based for testing. `RedisSessionBackend` with connection pool, fallback to in-memory when redis unavailable. `DatabaseSessionBackend` Postgres-backed with `session_variables` table, scope-aware retrieval (PLAN→BOT→SYS fallback chain). Consistent hashing for Redis horizontal scaling via key pattern. | ✅ |
| 8.3 | **Configuration Management** — `ConfigManager` with 4-layer priority (DEFAULT→ENV→FILE→RUNTIME). `set()`/`set_default()`/`set_many()`/`set_defaults()` APIs. Env var interpolation (`${VAR_NAME}`) with depth protection. Section access via `get_section(prefix)`. File loading from `.json`, `.yaml`/`.yml`, `.toml`, `.env` formats. `ConfigValidator` with type checking and enum validation. `ConfigWatcher` polls file mtime for hot reload without restart. `ProviderConfig`/`AgentConfig`/`DeploymentConfig` dataclasses with `from_config()` factory. `create_default_config()` with sensible defaults for all major sections. | ✅ |
| 8.4 | **Database Infrastructure** — `DatabaseManager` with Postgres connection, `execute()`/`execute_many()`/`health_check()`/`close()`. `DatabaseConfig` with URL, pool sizing, vector dimension, statement timeout. `MigrationManager` with version tracking via `_schema_version` table, `apply()` (idempotent), `get_current_version()`, `list_applied()`. `create_checkpointer_tables()` DDL for checkpoint/checkpoint_blobs/checkpoint_writes/checkpoint_mappings/store/store_blobs tables. `create_pgvector_extension()` for vector search support. `create_session_tables()` for session variable persistence. `BackupStrategy` dataclass for scheduling and retention. | ✅ |
| 8.5 | **LocalShellBackend & Sandbox Integration** — `LocalShellBackend` extends `FilesystemBackend` with `execute()` (subprocess with timeout). `ContainerSandbox` Docker-based with `execute`/`upload_files`/`download_files` via docker exec/cp, memory/CPU limits, `start()`/`stop()` lifecycle. `LangSmithSandbox` stub for remote sandbox integration. `RoleBasedSandboxSelector` selects sandbox type by environment (dev→local, production→container) and role (customer-support vs operator). `SandboxType` enum. Security: dev-only warnings, timeout enforcement on all execute operations, path traversal blocking. | ✅ |

**Key implementation details:**
- `FilesystemBackend._resolve()` uses `os.path.normpath` + prefix check to block path traversal outside `root_dir`
- `StateBackend` normalizes all paths via `_norm()` stripping leading `/` for consistent key handling
- `CompositeBackend._select()` uses fnmatch for route matching; `upload_files()` groups by resolved backend
- `SessionVariable._detect_type()` uses `isinstance` checks in priority order: bool→int→float→str→list→dict→None
- `InMemorySessionBackend.get_variable()` tries PLAN scope first (exact session+plan), then BOT (any session), then SYS (global) — enables scope fallback
- `ConfigManager._interpolate()` resolves `${VAR_NAME}` with depth limit of 3 to prevent infinite recursion from circular references
- `ConfigWatcher` runs in a daemon thread with configurable poll interval (default 5s)
- `DatabaseManager` uses `autocommit=True` psycopg connection; `is_connected` property reflects connection state
- `MigrationManager.apply()` is idempotent — skips already-applied versions by checking current version
- `checkpointer_tables()`/`session_tables()` return False immediately if not connected (no silent success)
- `ContainerSandbox._container_exec()` wraps docker commands with `timeout` prefix and `shlex.quote` for safety
- `LocalShellBackend.execute()` runs subprocess in `root_dir` working directory with shell=True

**New files:**
- `src/backends/__init__.py` — Package public API (30+ symbols re-exported)
- `src/backends/protocol.py` — `BackendProtocol`, `SandboxBackendProtocol`, `BaseSandbox`, `FileInfo`, `BackendResult`
- `src/backends/implementations.py` — `StateBackend`, `FilesystemBackend`, `CompositeBackend`
- `src/backends/session.py` — `SessionStateBackend`, `InMemorySessionBackend`, `RedisSessionBackend`, `DatabaseSessionBackend`, `SessionVariable`, `VariableScope`
- `src/backends/config.py` — `ConfigManager`, `ConfigWatcher`, `ProviderConfig`, `AgentConfig`, `DeploymentConfig`, `create_default_config`
- `src/backends/database.py` — `DatabaseManager`, `DatabaseConfig`, `MigrationManager`, `create_checkpointer_tables`, `create_pgvector_extension`, `create_session_tables`, `BackupStrategy`
- `src/backends/sandboxed.py` — `LocalShellBackend`, `ContainerSandbox`, `LangSmithSandbox`, `RoleBasedSandboxSelector`, `SandboxType`

**Tests:** `test_backends.py` — 105 test cases covering all 5 subtasks

---

## [0.3.1] — 2026-09-09

### Task 7: Routing & Control Flow ✅

Built a comprehensive routing and control flow system enabling conditional branching, dynamic dispatch, loops/recursion, human-in-the-loop interruption, task dispatch with version-aware handlers, workflow orchestration with DAG dependency resolution, circuit breaker, retry logic, and a typed event system.

| Subtask | Description | Status |
|---------|-------------|--------|
| 7.1 | **Conditional & Dynamic Routing** — `RouteCondition` with `route_fn` and priority ordering. `ConditionalRouter` evaluates state against ordered conditions (highest priority first). `PathMap` maps route function outputs to target node names with fallback default. `DynamicRouter` routes at runtime based on state content, with `route_all()` for fan-out and `to_send()` generating langgraph `Send()` objects. `MapReduceRouter` fan-out to worker nodes with round-robin distribution, and `fan_all()` broadcasting to all workers. `BranchSpec` for declarative conditional edges mimicking LangGraph's `add_conditional_edges`. | ✅ |
| 7.2 | **Loops & Recursion** — `LoopController` with break/continue/exit actions consumed via `check()`. `ForLoop` with fixed iteration count and body function. `WhileLoop` with condition-based iteration and max_iterations safety limit. `MapLoop` iterates over list items from state with programmatic body function. `NestedLoop` for subgraph loop coordination with parent-child controller propagation. `RecursionLimit` with `increment()` that raises `RecursionLimitExceeded` at max steps. `LoopDetector` with configurable sliding window (max_repeated_states up to 5, similarity_threshold default 0.8) using state hash tracking. | ✅ |
| 7.3 | **Human-in-the-Loop** — `InterruptSignal` with reason enum (APPROVAL_REQUIRED, INPUT_REQUIRED, TOOL_APPROVAL, MANUAL_INTERVENTION), configurable timeout, and serialization via `to_dict()`. `ResumeSignal` with interrupt_id, response, approved/denied flag. `ApprovalFlow` manages pending approvals with `check_timeouts()` for auto-resolve and `get_resolved()` retrieval. `InputCollector` with `request_input()`/`submit_input()` for mid-execution human prompts. `HumanInTheLoopMiddleware` wraps tool execution with approval gates via `interrupt_on` dict and exposes 3 agent tools: `request_approval`, `request_input`, `check_approvals`. | ✅ |
| 7.4 | **Task Dispatch & Workflow Engine** — `Task` immutable definition with task_id, task_type, version (semver), payload, priority, tags. `HandlerRegistry` stores handlers per type with version-aware resolution (exact match first, major version fallback, highest version default). `TaskDispatcher` routes tasks to handlers, records execution history. `Workflow` with DAG step definition (`depends_on`), `get_ready_steps()` for frontier detection, and concurrent ready-step execution via `asyncio.gather`. `TaskTree` tracks parent-child task hierarchy with `get_path_to_root()` and depth calculation. | ✅ |
| 7.5 | **Event System & Error Handling** — `SystemEvent` with 15 typed `EventType` constants across routing/dispatch/HITL/circuit/workflow domains. `EventBus` with type-based subscription and wildcard handlers, 1000-event circular history. `ErrorClassifier` with built-in defaults (TimeoutError→TEMPORARY, ValueError→PERMANENT, MemoryError→CRITICAL) and custom registration via `register()`. `CentralizedErrorHandler` runs registered callbacks and emits `ERROR_OCCURRED` events. `CircuitBreaker` with CLOSED→OPEN→HALF_OPEN state machine, configurable thresholds, and event emission on state transitions. `RetryHandler` with exponential backoff and retryable exception filtering. `MessageQueueEventProducer` stub for Kafka/ActiveMQ integration. | ✅ |

**Key implementation details:**
- `ConditionalRouter.route()` raises `NoRouteMatch` when no condition matches; use `route_with_default()` for fallback
- `DynamicRouter.add_route()` takes a `DynamicRoute` dataclass (name, description, target, condition_fn), not positional args
- `MapReduceRouter.fan_out()` distributes items round-robin across worker nodes, adding `_map_index` to each Send's state
- `LoopController.check()` consumes the action (resets to NONE) — must be called each iteration
- `WhileLoop` raises `RuntimeError` when `max_iterations` is exceeded (default 1000)
- `LoopDetector` uses simplified state hashing (only primitive values, list/tuple lengths, type names) to avoid hash collisions from complex objects
- `ApprovalFlow.check_timeouts()` returns auto-resolved `ResumeSignal`s with `metadata={"reason": "timeout"}`
- `HumanInTheLoopMiddleware.set_interrupt(tool_name, True/False)` dynamically enables/disables per-tool approval gates
- `HandlerRegistry` sorts handlers by version descending for highest-version default resolution
- `Workflow.run()` uses `asyncio.gather` for concurrent ready-step execution; failed dependencies cause dependent steps to be auto-skipped
- `CircuitBreaker` state transitions emit `SystemEvent` via `asyncio.ensure_future` for non-blocking event delivery
- `RetryHandler` default retryable exceptions: TimeoutError, ConnectionError, ConnectionRefusedError, ConnectionResetError — non-retryable exceptions propagate immediately

**New files:**
- `src/routing/__init__.py` — Package public API (40+ symbols re-exported)
- `src/routing/conditional.py` — `RouteCondition`, `ConditionalRouter`, `PathMap`, `DynamicRouter`, `DynamicRoute`, `MapReduceRouter`, `BranchSpec`, `NoRouteMatch`
- `src/routing/loops.py` — `LoopController`, `LoopAction`, `ForLoop`, `WhileLoop`, `MapLoop`, `NestedLoop`, `RecursionLimit`, `RecursionLimitExceeded`, `LoopDetector`, `LoopDetectionConfig`
- `src/routing/hitl.py` — `InterruptSignal`, `InterruptReason`, `ResumeSignal`, `ApprovalFlow`, `InputCollector`, `HumanInTheLoopMiddleware`
- `src/routing/workflow.py` — `Task`, `TaskResult`, `TaskStatus`, `HandlerRegistry`, `TaskDispatcher`, `Workflow`, `WorkflowStep`, `WorkflowStepStatus`, `WorkflowResult`, `TaskTree`
- `src/routing/events.py` — `SystemEvent`, `EventType`, `EventBus`, `ErrorClassifier`, `ErrorCategory`, `ErrorSeverity`, `CentralizedErrorHandler`, `CircuitBreaker`, `CircuitState`, `RetryHandler`, `MessageQueueEventProducer`

**Tests:** `test_routing.py` — 175 test cases covering all 5 subtasks

---

## [0.3.0] — 2026-09-09

### Task 6: Streaming & Observability ✅

Built a real-time streaming pipeline for agent output, transport layer with retry/cancellation, output formatters (Chatbox NDJSON, OpenAI SSE, Claude SSE), observability system (metrics, tracing, health checks, debug mode), and gateway integration for UI communication via HTTP and WebSocket.

| Subtask | Description | Status |
|---------|-------------|--------|
| 6.1 | **StreamChunk Schema & Producers** — Universal chunk dataclass (`StreamChunk`) with content, reasoning, tool call deltas, tool results, finish reason. Producers: `SimulatedProducer` (test data), `LangGraphProducer` (wraps `CompiledStateGraph.astream()`), `OpenAIProducer` (wraps OpenAI streaming API). | ✅ |
| 6.2 | **Stream Transport Layer** — `StreamTransport` forwards chunks through a `Tee` fan-out to multiple consumers. `RetryPolicy` with exponential backoff (default 3 attempts, statuses 429/502/503/504). `CancelToken` for cooperative cancellation. `StreamCollector` for debugging, `FileDebugPrinter` for trace output. | ✅ |
| 6.3 | **Stream Formatters** — `ChatboxFormatter` (NDJSON lines for production), `OpenAIFormatter` (SSE `data:` lines matching OpenAI Chat Completions streaming spec), `ClaudeFormatter` (SSE block-based: `text_delta`, `thinking_delta`, `tool_call_delta`, `tool_result`, `message_stop`). `FormatterFactory` for dynamic resolution with custom formatter registration. | ✅ |
| 6.4 | **Observability & Tracing** — `MetricsCollector` (token usage, tool execution time, streaming latency, error rate, iterations). `Tracer` with span-based tracing (trace/span lifecycle, parent-child hierarchy, duration tracking). `StructuredLogger` (JSON-formatted log events). `HealthCheck` with component status tracking (`ok`/`degraded`/`error`), uptime, error rate per minute. `DebugMode` with step-by-step state snapshots and truncation. | ✅ |
| 6.5 | **Gateway Integration** — `HTTPGateway` (POST NDJSON chunks, auth headers, persistent `httpx.AsyncClient` session). `WebSocketGateway` (real-time push, auto-reconnect, JSON framing). `GatewayManager` (multi-gateway orchestration, consumer factory for `Tee` integration). `BackpressureController` (block/drop/throttle strategies). `BatchBuffer` (size-based + interval-based flushing). Event type classification (`reasoning`, `content`, `tool_call`, `tool_result`, `error`, `finish`). | ✅ |

**Key implementation details:**
- `StreamChunk.to_dict()` serializes all fields to JSON-compatible format, truncating tool result data to 1000 chars
- `StreamTransport.run_and_collect()` provides a convenience method to run the full pipeline and capture all chunks
- `Tee.emit()` automatically detects async vs sync consumers and awaits accordingly
- `FormatterFactory` supports custom formatter registration via `register()` for extensibility
- `Tracer` maintains a span stack for parent-child relationships; `end_trace()` closes all open spans
- `MetricsCollector` is thread-safe with a reentrant lock; `snapshot()` captures point-in-time readings
- `DebugMode._truncate_state()` prevents context window overflow by truncating large strings (>200 chars) and long lists (>50 items)
- `GatewayManager.create_consumer()` produces a callable suitable for direct use with `Tee`/`StreamTransport`
- `HealthCheck` aggregates component statuses into an overall status: any `error` → `"error"`, any `degraded` → `"degraded"`
- `BackpressureController` with `"drop"` strategy tracks dropped chunk count via `dropped_count` property

**New files:**
- `src/streaming/__init__.py` — Package public API (all 25+ symbols re-exported)
- `src/streaming/producers.py` — `StreamChunk`, `ToolCallDelta`, `StreamProducer`, `SimulatedProducer`, `LangGraphProducer`, `OpenAIProducer`
- `src/streaming/transport.py` — `StreamTransport`, `Tee`, `RetryPolicy`, `CancelToken`, `CancelledError`, `StreamCollector`, `FileDebugPrinter`
- `src/streaming/formatters.py` — `ChatboxFormatter`, `OpenAIFormatter`, `ClaudeFormatter`, `StreamFormatter`, `FormatterFactory`
- `src/streaming/observability.py` — `MetricsCollector`, `Tracer`, `Span`, `HealthCheck`, `HealthStatus`, `DebugMode`, `DebugSnapshot`, `StructuredLogger`
- `src/streaming/gateway.py` — `HTTPGateway`, `WebSocketGateway`, `GatewayManager`, `GatewayConfig`, `BackpressureController`, `BatchBuffer`, `GatewayEventType`, `classify_chunk`

**Tests:** `test_streaming.py` — 89 test cases covering all 5 subtasks

---

## [0.2.5] — 2026-09-09

### Task 5: Subagent Communication ✅

Built a full subagent system enabling agents to spawn, communicate, and coordinate with sub-agents — supporting synchronous invocation, asynchronous background tasks, inter-agent messaging via a broker/event-bus pattern, parallel tool execution, and profile-based resource management.

| Subtask | Description | Status |
|---------|-------------|--------|
| 5.1 | **Sync SubAgent** — `SubAgent` declarative spec (name, description, system_prompt, model, tools, middleware). `CompiledSubAgent` wrapper with `invoke()` that runs the middleware chain. `SubAgentRegistry` for register/get/unregister/list. `SubAgentMiddleware` injects a `task` tool so the main agent can spawn subagents by name with input data. Built-in `DEFAULT_SUBAGENT_SPEC` ("general_purpose") auto-registered. | ✅ |
| 5.2 | **Async SubAgent** — `AsyncSubAgent` spec with remote deployment support (`graph_id`, `url`, `headers`). `AsyncSubAgentManager` with lifecycle tracking (launch_task, get_task_status, cancel_task, list_tasks, clean_orphans). Background thread execution for local subagents, HTTP-based remote execution via LangGraph SDK. Concurrent task limiting (`max_concurrent`). `AsyncSubAgentMiddleware` provides 4 tools: `launch_task`, `get_task_status`, `cancel_task`, `list_tasks`. | ✅ |
| 5.3 | **Communication Protocol** — `AgentMessage` dataclass with sender, recipient, message_type (RESULT, STATE_UPDATE, COMMAND, EVENT, REQUEST, RESPONSE, ERROR), payload, priority, correlation_id. `MessageBroker` with per-recipient queues, FIFO ordering, `send()`/`receive()`/`poll()`/`clear_recipient()`. `EventBus` with subscribe/unsubscribe/emit/clear, wildcard `*` support. `SharedState` thread-safe key-value store with `update(key, func)` for atomic transformations. `CommunicationMiddleware` provides `send_message`, `read_state`, `write_state` tools. | ✅ |
| 5.4 | **Parallel Tool Execution** — `ParallelExecutor` using `concurrent.futures.ThreadPoolExecutor` with configurable `max_workers`. `ParallelToolCall` (id, tool_name, args, kwargs). `ParallelToolResult` wrapping `ToolResult` with duration_ms. `BatchResult` with success/failure counts, aggregated duration, `to_dict()` for reporting. Error isolation (one failing tool does not affect others). Per-tool timeout enforcement. Optional `stream_callback` for real-time per-tool progress. | ✅ |
| 5.5 | **Profile & Resource Management** — `SubagentProfile` with name, description, system_prompt, model, tool_visibility, max_subagents, max_concurrent_async, token_budget, timeout, metadata. Profile inheritance via `inherit()` (creates new profile without mutating parent). `GeneralPurposeSubagentProfile()` factory with sensible defaults. `ResourceManager` enforces limits: `acquire_slot()`/`release_slot()` for sync, `acquire_async_slot()`/`release_async_slot()` for async, token budget tracking via `check_token_budget()`/`record_token_usage()`, orphan cleanup. `LifecycleManager` with full state machine (CREATED → RUNNING → COMPLETED/FAILED/TIMED_OUT/CANCELLED). | ✅ |

**Key implementation details:**
- `CompiledSubAgent.invoke()` runs the middleware stack's `run_before_agent()` with the input state
- SubAgentRegistry errors as `ToolResult(success=False, error=...)` instead of raising — safe for LLM tool-calling
- Async task status polling uses `get_task_status()` returning a dict with id, status, result, timing
- MessageBroker emits `AgentEvent` on every `send()` via its internal EventBus — enables cross-cutting monitoring
- `ParallelExecutor` not configurable via `tool_executor` kwarg; it resolves tools from the injected `ToolRegistry`
- Profile inheritance does NOT modify the parent — `inherit()` performs a deep copy before applying overrides

**New files:**
- `src/subagents/__init__.py` — Package public API (all 20+ symbols re-exported)
- `src/subagents/sync.py` — `SubAgent`, `CompiledSubAgent`, `SubAgentRegistry`, `SubAgentMiddleware`, `DEFAULT_SUBAGENT_SPEC`
- `src/subagents/async_sub.py` — `AsyncSubAgent`, `AsyncSubAgentManager`, `AsyncSubAgentMiddleware`, `AsyncSubAgentStatus`, `AsyncTask`
- `src/subagents/communication.py` — `MessageBroker`, `EventBus`, `SharedState`, `AgentMessage`, `AgentEvent`, `CommunicationMiddleware`, `MessageType`
- `src/subagents/parallel.py` — `ParallelExecutor`, `BatchResult`, `ParallelToolCall`, `ParallelToolResult`
- `src/subagents/profiles.py` — `SubagentProfile`, `GeneralPurposeSubagentProfile`, `ResourceManager`, `LifecycleManager`, `SubagentLifecycle`, `SubagentState`, `ResourceExhaustedError`

**Tests:** `test_subagents.py` — 105 test cases covering all 5 subtasks

---

## [0.2.0] — 2026-09-09

### Task 4: Memory & Persistence ✅

Built a complete memory and persistence system with checkpoint-based short-term memory, namespaced long-term memory store, memory middleware for agent context injection, a background "dreaming" self-improvement subsystem, and memory compaction/cleanup utilities.

| Subtask | Description | Status |
|---------|-------------|--------|
| 4.1 | **Checkpointer Backend** — `PostgresStore` and `InMemoryStore` implementations of LangGraph's `BaseCheckpointSaver`. Checkpoint schema with version, channel values/versions, pending writes. `get_store(db_url)` factory selects implementation based on URL. `close_store()` for proper connection teardown. Time travel and replay support via `get_tuple()` with thread/checkpoint config. | ✅ |
| 4.2 | **Session Memory Management** — Thread-based session lifecycle tracking. Checkpoint serialization and deserialization. Session CRUD operations using the checkpointer API. Cross-turn state preservation through LangGraph's checkpoint-per-step model. | ✅ |
| 4.3 | **Long-term Memory Store** — `BaseStore` abstraction with `put()`/`get()`/`search()`/`delete()`. `InMemoryStore` and `PostgresStore` implementations. Namespace isolation (user-based, bot/tenant-based, global). Semantic search support via pgvector in PostgresStore. Cross-session persistence for user preferences, facts, and learned information. | ✅ |
| 4.4 | **Memory Middleware** — Injects AGENTS.md, MEMORY.md, USER.md, IDENTITY.md files into agent context each turn. Static file injection with prompt caching headers. HTML comment stripping. Progressive disclosure strategy to manage context window usage. | ✅ |
| 4.5 | **Dreaming System** — Background self-improvement subsystem: `ScanSystem` discovers threads via `scan_thread_ids()`, `Dream Engine` synthesizes facts/lessons/conflict markers from conversation history, `Consolidation` writes insights into the long-term store under `memories/`, `system.lessons/`, `system.conflict_markers/` namespaces. `AlertsSystem` with heartbeat monitoring and backlog tracking. Fixed LangGraph 1.x API compatibility (removed deprecated `DeltaChannel`/`_messages_delta_reducer` imports, uses `checkpointer.get_tuple()` directly). | ✅ |
| 4.6 | **Memory Compaction & Cleanup** — Orphan checkpoint cleanup (stale threads without recent activity). TTL-based eviction for expired memories. Store compaction utilities to reclaim space and maintain performance. | ✅ |

**Key implementation details:**
- Dreaming `load_thread_messages()` uses `checkpointer.get_tuple(config)` which returns `(Checkpoint, list[PendingWrite])` — the `DeltaChannel` pattern removed for langgraph 1.x
- `enqueue.py` middleware fixed to use `src.middleware.types.AgentMiddleware` (not the removed `langchain.agents.middleware` path) with async `before_agent(config)`/`after_agent(config)` hooks
- `consolidate.py` uses `src.memory.store.close_store()` for proper cleanup
- `get_store(db_url=None)` returns `InMemoryStore` by default, `PostgresStore` when a `db_url` is provided

**New files:**
- `src/memory/checkpointer.py`, `src/memory/checkpoint.py`, `src/memory/store.py` — Checkpointer backend and store factories
- `src/memory/backend.py`, `src/memory/memory_backend.py`, `src/memory/namespace.py` — Memory backend and namespace management
- `src/memory/memory_middleware.py` — Memory injection middleware
- `src/memory/cleanup.py` — Compaction, TTL eviction, orphan cleanup
- `src/memory/dreaming/__init__.py`, `loader.py`, `enqueue.py`, `dream.py`, `consolidate.py`, `scan.py`, `alerts.py` — Dreaming system (7 files)

**Tests:** `test_memory.py` — 57 test cases

---

## [0.1.5] — 2026-09-09

### Task 3: Tool System ✅

Built a complete tool management system with registry, filesystem tools, MCP (Model Context Protocol) integration, sandboxed execution, permission system, and tool discovery.

| Subtask | Description | Status |
|---------|-------------|--------|
| 3.1 | **Tool Registry & Discovery** — `ToolRegistry` singleton with `register()`/`get()`/`unregister()`/`list()`/`search()` by name, description, or tags. `ToolSpec` dataclass (name, description, fn, category, tags, timeout, retry_policy). Auto-discovery via `discovery.py` scans for tool-decorated functions. | ✅ |
| 3.2 | **Tool Execution & Error Handling** — `ToolResult` dataclass with success, data, error, metadata, evicted flag. Large result eviction (>20K chars auto-evicted). Execution pipeline with per-tool timeout and retry. Consistent error propagation via `ToolResult(success=False, error=...)`. | ✅ |
| 3.3 | **Filesystem Tools** — `ls` (list directory), `read_file` (with offset/limit), `write_file` (overwrite), `edit_file` (find-and-replace), `delete` (file/directory), `glob` (pattern matching), `grep` (text search), `execute` (bash with timeout). All integrated with the permission system. | ✅ |
| 3.4 | **MCP Tool Integration** — MCP client supporting stdio and SSE transports. Tool discovery via MCP `tools/list`. Name prefixing (`mcp__server__{name}-{tool}`) to avoid collisions. Execution bridging from MCP tool calls to local tool handling. Server lifecycle management (start/stop/health). Multi-server support. | ✅ |
| 3.5 | **Sandbox & Permission System** — `FilesystemPermission` dataclass (operations, paths, mode allow/deny/interrupt). Role-based access (customer-support vs operator). Human-in-the-loop (HITL) interrupt for sensitive operations. Audit logging with query API for compliance. | ✅ |
| 3.6 | **Tool Description & Discovery** — Tool description overrides for LLM-facing documentation. Discovery by name, description, and tag matching. Dynamic tool selection based on conversation context. Usage statistics collection for tool optimization. Cost tracking per tool invocation. | ✅ |

**New files:**
- `src/tools/registry.py`, `src/tools/__init__.py` — Registry and public API
- `src/tools/filesystem.py` — ToolResult dataclass and all filesystem tools
- `src/tools/mcp.py` — MCP client adapter with stdio/SSE support
- `src/tools/permissions.py` — PermissionManager and FilesystemPermission
- `src/tools/sandbox.py` — Sandbox execution isolation
- `src/tools/discovery.py` — Tool auto-discovery

**Tests:** `test_tools.py` — 94 test cases

---

## [0.1.0] — 2026-09-09

### Task 1: Agent Graph Core ✅

Built the core graph engine based on LangGraph Pregel — the foundational layer for the entire agent. Includes state management, node definitions, channel-based state management, graph compilation, execution loop, error handling, visualization, subgraph support, and DeepAgents integration.

| Subtask | Description | Status |
|---------|-------------|--------|
| 1.1 | **Graph Types & State Definitions** — `AgentState` schema with `Annotated[messages, add_messages]`, metadata/context/current_step fields. `Command` dataclass for graph control (goto, update, interrupt). TypedDict + dataclass support for flexible state schemas. `ChannelEndpoint` for channel-based routing. | ✅ |
| 1.2 | **Graph Builder & Topology** — `GraphBuilder` class with `add_node()`/`add_edge()`/`set_entry_point()`/`set_finish_point()`. `build_agent()` factory function. `ChannelFactory` for creating typed channels. Conditional edge wiring with routing functions. Support for both function-based (`@node`) and class-based nodes. | ✅ |
| 1.3 | **Node Implementations** — `AgentNode` base class with lifecycle hooks (before_node, execute, after_node). `ToolNode` for tool execution. Conditional edge helpers for dynamic routing based on agent state. Support for parallel node execution. | ✅ |
| 1.4 | **Reducer System** — Custom reducer functions for state updates. Support for nested state reduction. Message append/merge reducers. Integration with LangGraph's `Annotated` type system. | ✅ |
| 1.5 | **Error Handling & Retry** — `AgentError` exception hierarchy. Retry policies with configurable max_attempts, backoff (exponential), retry_on conditions. Timeout policies per node. Fallback node handlers for graceful degradation. Error propagation from subgraph to parent. | ✅ |
| 1.6 | **Subgraph Support** — Nested graph composition with namespace isolation. Parent-child `Command` protocol for cross-graph communication. Context isolation between subgraphs. Recursion limits to prevent infinite loops. Checkpoint separation per subgraph boundary. | ✅ |
| 1.7 | **Runtime & Execution Loop** — `StreamingRuntime` class for streaming graph execution. Event loop management with async/await support. Concurrency handling for parallel branches. Superstep BSP iteration (Plan → Execute → Update). Human-in-the-loop interrupt/resume via checkpoint injection. | ✅ |
| 1.8 | **Channel Management** — Custom channel types: `LastValue`, `BinaryOperatorAggregate`, `Topic`, `EphemeralValue`. Channel I/O with read/write operations. Version tracking for trigger detection. Pending writes buffer for crash recovery. Channel persistence integration with checkpointing. | ✅ |
| 1.9 | **Graph Visualization** — Mermaid.js graph generation for documentation. DOT format export for Graphviz rendering. ASCII graph visualization for terminal debugging. Step-by-step debug mode with state inspector. | ✅ |

**New files:**
- `src/graph/types.py`, `src/graph/builder.py`, `src/graph/node.py` — Core graph types, builder, and nodes
- `src/graph/reducers.py`, `src/graph/errors.py` — Reducer system and error handling
- `src/graph/subgraph.py`, `src/graph/runtime.py`, `src/graph/channels.py` — Subgraph, runtime, channels
- `src/graph/visualization.py`, `src/graph/integration.py` — Visualization and DeepAgents integration

**Tests:** 8 test files — `test_graph_builder.py`, `test_graph_types.py`, `test_graph_reducers.py`, `test_graph_errors.py`, `test_graph_subgraph.py`, `test_graph_runtime.py`, `test_graph_channels.py`, `test_graph_visualization.py` — 129 total test cases

### Task 2: Middleware Stack ✅

Built the middleware pipeline system inspired by orchestrator's pattern — enabling composable, ordered middleware that wraps agent execution with pre/post hooks, tool injection, security checks, summarization, progress tracking, rubric evaluation, and stack compilation.

| Subtask | Description | Status |
|---------|-------------|--------|
| 2.1 | **Middleware Types & Interfaces** — `AgentMiddleware` abstract base class with lifecycle hooks: `before_agent()`, `after_agent()`, `wrap_model_call()`, `awrap_model_call()`, `modify_request()`, `before_model()`. Properties for name, order, state_schema, tools, system_prompt. `MiddlewareConfig` dataclass for configuration propagation. `MiddlewareStack` for registration and ordering. | ✅ |
| 2.2 | **Tool Injection Middleware** — `ToolMiddleware` that registers tools from a `ToolRegistry` into the agent's available tool set. Tool enable/disable at runtime. Dynamic tool selection based on context. Integration with the main agent's tool calling loop. | ✅ |
| 2.3 | **Security & Permissions Middleware** — Input validation for injection prevention (prompt injection, code injection). Sandbox enforcement boundary. PII detection and redaction (email, phone, ID patterns via configurable regex). Role-based access control integration with `PermissionManager`. HITL interrupt for sensitive operations. | ✅ |
| 2.4 | **Summarization Middleware** — Automatic context compaction when token thresholds are exceeded (fraction-based, absolute token count, message count). Keep-window strategy to preserve recent messages. Offload to long-term storage for evicted content. Media handling for large attachments. Prompt caching optimization. | ✅ |
| 2.5 | **Progress & Logging Middleware** — `ProgressMiddleware` emits execution events (node_start, node_end, tool_call, tool_result, error). Execution tracking with timing. Structured logging for every agent operation. `TodoListMiddleware` with `write_todos` tool for real-time task tracking visible to the user. | ✅ |
| 2.6 | **Rubric Evaluation Middleware** — Criteria-based response evaluation (identity/critical/simple tiers). Grader sub-agent for scoring. Revision loop (re-generate on failure, up to configurable max retries). Nested rubric support for hierarchical criteria. Configurable passing threshold. Streaming-compatible evaluation. | ✅ |
| 2.7 | **Middleware Stack Compilation & Execution** — 3-segment assembly (base stack, caller middlewares, tail stack). Merge strategy: replace vs append. Middleware exclusion by name or type. Validation for ordering constraints. `CompiledMiddlewareStack` with `run_before_agent()`/`run_after_agent()` returning `(state, should_halt)`. | ✅ |

**New files:**
- `src/middleware/types.py` — `AgentMiddleware` ABC, `MiddlewareConfig`
- `src/middleware/stack.py` — `MiddlewareStack`, `CompiledMiddlewareStack` (compilation + execution)
- `src/middleware/tooling.py` — `ToolMiddleware` (tool injection)
- `src/middleware/security.py` — `SecurityMiddleware` (PII, injection, sandbox)
- `src/middleware/summarization.py` — `SummarizationMiddleware` (auto-compaction)
- `src/middleware/progress.py` — `ProgressMiddleware` (events, timing)
- `src/middleware/rubric.py` — `RubricMiddleware` (evaluation, revision)

**Tests:** `test_middleware.py` — 61 test cases

---

## Summary

| Metric | Value |
|--------|-------|
| **Current version** | 0.6.0 |
| **Tasks completed** | 10 / 10 |
| **Subtasks completed** | 73 / 73 |
| **Total tests** | 1132+ (129 graph + 61 middleware + 94 tools + 57 memory + 105 subagents + 89 streaming + 175 routing + 105 backends + 27 api + 105 deploy ops + 160 advanced features + 25 dreaming) |
| **Source files** | 92+ Python files |
| **Total lines of code** | ~22,000 LOC |
| **Package** | `deepagents-vertex-agent` |
| **Python** | >= 3.11 |
| **Core dependencies** | `deepagents==0.7.9`, `langgraph==1.2.11`, `langchain==1.3.18` |

---

*Last updated: 2026-09-09*
