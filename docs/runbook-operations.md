# Runbook — Operations: tool failure, memory conflict, context overflow, checkpointer DB loss

Repo: deepagents 0.7.9 / langgraph 1.2.11 / langchain-core 1.6.0 /
langgraph-checkpoint-postgres 3.1.2 / langgraph-cli 0.4.31. Postgres via
`infra/docker-compose.yml`.

Covers run-time failure modes an operator will actually hit, with detection,
mitigation, and concrete code/test/entrypoint references. Cross-links:
`docs/runbook-observability.md` (LangSmith tracing) and
`docs/tool-audit-checklist.md` (tool surface). Deployment artifact details:
`docs/phase-0-discovery.md` §17.

---

## 0. Quick orientation — the pieces

| Concern | Code | Entrypoint |
|---|---|---|
| Single graph construction point | `src/agent/graph.py::build_agent` | (library) |
| Server entrypoint (deployment) | `src/agent/server.py::graph` | `langgraph up` / `dockerfile` |
| Session short-term memory | `src/memory/checkpointer.py::get_checkpointer` | `python -m src.memory.cleanup` |
| Long-term / per-user memory | `src/memory/store.py::get_store`, `src/memory/memory_backend.py` | (library) |
| Dreaming graph | `src/memory/dreaming/dream.py::build_dream_agent` | `python -m src.memory.dreaming.scan` |
| Consolidation / aging | `src/memory/dreaming/consolidate.py` | `python -m src.memory.dreaming.consolidate` |
| Dreaming health alerting | `src/memory/dreaming/alerts.py` | `python -m src.memory.dreaming.alerts` |
| Concurrency load test | `src/api/load_test.py::run_concurrent_sessions` | `python -m src.api.load_test` |
| Per-user rate limiting | `src/api/rate_limit.py::RateLimiter` | `python -m src.api.rate_limit` (demo) |

---

## 1. Tool failure (custom or built-in)

**Symptom.** The agent's turn ends with an error instead of an answer; a
`ToolMessage` carries an exception string; the model keeps retrying the same
call in a loop, or the turn stops early. In LangSmith the failing run's tool
run shows an exception (observability: `docs/runbook-observability.md` §4).

**Detection.**
- Built-in filesystem tools return `ToolMessage` errors like
  `"Error: permission denied for read/write on <path>"` when gated by
  `FilesystemPermission` (discovery §16.2); `permission` gating is checked in
  `src/agent/tools/` tests (`tests/test_tools.py::test_restricted_sandbox_*`).
- Custom tools: `src/agent/tools/` — `query_order` errors on an unknown id
  (`tests/test_tools.py::test_query_order_unknown_id_error`); `create_support_ticket`
  appends and returns an id (`test_create_support_ticket_appends_and_returns_id`).
- The Task 2 sandbox (`src/agent/tools/sandbox.py`) raises on destructive /
  escaping commands — see `tests/test_tools.py::test_restricted_sandbox_*`.
- Tool audit checklist: `docs/tool-audit-checklist.md`.

**Mitigation.**
1. Reproduce with a deterministic fake model so the tool path is isolated from
   model variability (Ruling M1): `tests/fake_model.py::ScriptedChatModel`.
2. For oversized outputs, the `LimitToolOutputMiddleware` truncates a single
   `ToolMessage` to `DEFAULT_MAX_LENGTH` (4000 chars) — see
   `src/agent/context/limit_output.py`. If a tool returns a *huge* blob and the
   agent stalls, this middleware is the mitigation.
3. A tool that is unusable for a role is excluded via `HarnessProfile.excluded_tools`
   (see `tests/test_tools.py::test_customer_support_role_excludes_execute`).
4. Check the sandbox timeout / argv-only execution if `execute` is the failing
   tool (`src/agent/tools/sandbox.py`).

---

## 2. Memory conflict / contradictory long-term memory

**Symptom.** The agent recalls contradicting facts (e.g. a user's remembered
preference changed), gives a wrong answer seemingly sourced from stale memory.

**Detection.**
- The dreaming graph writes user facts into `("memories", <user_id>)`,
  lessons into `("system", "lessons")`, and detected contradictions into
  `("system", "conflict_markers")` but **never overwrites an existing memory**
  (S8). Conflicts are surfaced as *markers*, not merged — see
  `src/memory/dreaming/dream.py::write_dream_results` and
  `tests/test_dreaming.py::test_conflict_does_not_overwrite_existing_memory_and_records_marker`.
- The memory backend resolution lives in `src/memory/memory_backend.py`
  (`runtime.context.user_id` → namespace); a user invoked *without*
  `context=UserContext(user_id=...)` raises a clear error rather than silently
  writing to a shared namespace (`tests/test_long_term_memory.py::test_missing_user_context_raises_clear_error`).

**Mitigation.**
1. Inspect the user's memory namespace for duplicated entries:
   `python -m src.memory.dreaming.consolidate --db-url <url> --user <user_id>`
   merges duplicate *normalized* content and de-prioritizes stale items
   (idempotent, never deletes non-duplicates; see `consolidate.py`).
2. Check `("system", "conflict_markers")` for recorded conflicts — these are
   the honest "I may contradict myself" signals.
3. The memory guidance prompting is in
   `src/agent/graph.py::MEMORY_GUIDANCE` / `build_system_prompt` — the agent is
   told to re-read `/memory/notes.md` at session start. If an operator changes
   recall behavior, that prompt is the lever.
4. Re-verify isolation: `tests/test_long_term_memory.py::test_multi_user_namespace_isolation_within_one_store_via_writes`.

---

## 3. Context overflow

**Symptom.** The agent runs out of token window mid-turn; LangGraph raises a
`GraphRecursionLimit` / recursion error, or the turn degrades / drops older
messages the user expects retained. Slow turns near the context ceiling.

**Detection.**
- LangSmith run shows the run stopped with an error node /
  `GraphRecursionLimit` (`docs/runbook-observability.md` §4).
- The default summarization middleware compacts/trims to a `keep` window; a
  custom summarization is built via
  `src/agent/context/summarization.py::build_summarization_middleware`
  (default thresholds modest; `middleware=[...]` **replaces**, not stacks, the
  default — `tests/test_context.py::test_custom_middleware_replaces_default_not_stacked`).

**Mitigation.**
1. Tool-result blow-up: `LimitToolOutputMiddleware` (4000-char head-truncation)
   is the first line — `tests/test_context.py::test_tool_output_limiter_truncates_oversized_result`.
2. Message compaction: tune `keep` / `trim_tokens_to_summarize` in
   `build_summarization_middleware` — `tests/test_context.py::test_custom_low_threshold_compacts_and_trims_to_keep_window`.
3. Subagent isolation: the declarative subagent runs in its own graph state and
   returns only a compact summary via the `task` tool —
   `tests/test_context.py::test_research_subagent_context_isolation`
   (see `src/agent/context/subagents.py`).
4. If a single thread's history is too large, it can be cleared with the
   documented checkpointer cleanup API (`src/memory/cleanup.py` deletes inactive
   threads; see §5 for DB-loss recovery).

---

## 4. Checkpointer lost DB connection

**Symptom.** Production turns fail with connection errors (psycopg
`OperationalError`, connection refused/reset), or the server won't resume
threads. The in-memory dev fallback is silent — a prod outage appears as a
spike of DB errors.

**Detection.**
- `get_checkpointer(url)` / `get_store(url)` in
  `src/memory/checkpointer.py` / `src/memory/store.py` open a raw psycopg
  connection (`autocommit=True`, `row_factory=dict_row`) and run `setup()`.
  Connection failure surfaces at construction time.
- Health: `docker compose -f infra/docker-compose.yml ps` shows the `postgres`
  service health (`pg_isready`). A stopped DB ⇒ every saver/store open fails.
- Concurrency resilience against this exact stack:
  `tests/test_load_test.py::test_concurrent_sessions_isolated_over_postgres`
  exercises the shared `PostgresSaver` + `PostgresStore` for real; a DB drop
  would make it fail loudly.

**Mitigation.**
1. Bring the DB back: `docker compose -f infra/docker-compose.yml up -d postgres`,
   wait for healthy, then re-run the failing graph. The schemas are idempotent
   (`setup()` applies missing migrations), so no manual DDL is needed.
2. Data is persisted per-thread under `checkpoints` / `checkpoint_blobs` /
   `checkpoint_writes`; short-term session memory survives process restarts but
   is lost if the volume is destroyed. Long-term memory lives in the Store
   (same DB). Stale-thread pruning: `python -m src.memory.cleanup
   --database-url <url> --max-age-days N [--dry-run]`.
3. Do NOT silently fall back to `MemorySaver` in production: `get_checkpointer`
   only falls back to in-memory when **no** `DATABASE_URL` / url is provided.
   If an operator sees in-memory behavior in prod, it means the env var is
   unset — not that the DB is healthy.
4. Connection ownership note: the returned `PostgresSaver`/`PostgresStore` own
   a single open connection; close with `.conn.close()` when a long-lived
   worker is done (`_build_postgres_saver` / `_build_postgres_store`).

---

## 5. Dreaming job is down / backlog growing (alerting)

**Symptom.** No consolidation/dream output for a long time; memory never ages;
the pending (enqueued-but-not-dreamed) thread count climbs.

**Detection.** Run the health check (non-zero exit = operator action needed):

```bash
python -m src.memory.dreaming.alerts \
  --db-url "$DATABASE_URL" \
  --heartbeat-file /var/lib/vertex-agent/dream-heartbeat \
  [--max-age-seconds 3600] [--max-backlog 50]
```

- **Heartbeat**: the consolidate job (and optionally the cold scan) write a
  timestamped heartbeat file after a successful run
  (`consolidate.py --heartbeat-file`, `scan.py --heartbeat-file`). Missing or
  stale (> `--max-age-seconds`) ⇒ "dreaming job may be down".
- **Backlog**: threads present in the checkpointer
  (`loader.py::scan_thread_ids`) minus threads that have a dream artifact in
  the Store (`alerts.py::discover_dreamed_threads` — dream items carry
  `thread_id`). No durable broker exists (no Celery/BullMQ — ruling), so this
  honest durable count is the "queue" proxy.

**Mitigation / data source details.**
- Pure logic (deterministic, injectable clock): `alerts.py::check_health`,
  `is_heartbeat_stale`, `compute_backlog`; tests
  `tests/test_alerts.py::test_health_*`.
- Kicking a stalled pipeline: `python -m src.memory.dreaming.scan
  --db-url <url> --user <user_id> --model <cheap-model> [--heartbeat-file ...]`
  (dreams every thread for the user); then `python -m
  src.memory.dreaming.consolidate --db-url <url> --heartbeat-file ...`.
- Thresholds are honest defaults (`3600s` heartbeat, `50` backlog). Tune them;
  do not treat them as capacity guarantees — confirmed by
  `tests/test_alerts.py`.

---

## 6. Capacity / deployment sanity

- **Load test (concurrency on real Postgres)**:
  `python -m src.api.load_test --sessions 8 --turns 2 --db-url "$DATABASE_URL"`.
  Deterministic fake model, shared `PostgresSaver` + `PostgresStore`, N distinct
  `thread_id`s in parallel; asserts each session reads back **its own** fact
  (no cross-thread interference) and reports sessions/s. Integration test:
  `tests/test_load_test.py::test_concurrent_sessions_isolated_over_postgres`
  (skips when DB is down).
- **Server artifact**: `Dockerfile` is CLI-generated
  (`langgraph dockerfile ./Dockerfile`), `langgraph.json` maps `agent` →
  `./src/agent/server.py:graph`; `python_version` 3.11; `checkpointer: postgres`
  (Store index intentionally omitted so a bare boot needs no LLM/embedding key;
  add `store.index` only when enabling pgvector search). Validate:
  `langgraph validate`. Build: `langgraph build -t vertex-agent:latest`.
  See discovery §17.
- **Rate limiting** (front-door guard for a future gateway; Ruling M4):
  `src/api/rate_limit.py::RateLimiter.allow(user_id, cost)`; tests
  `tests/test_rate_limit.py::test_concurrent_allows_do_not_overspend`.

---

## 7. Decision tree (fast triage)

1. Turn failed on a tool? → §1 (sandbox/timeout/limit-output).
2. Wrong answer from stale/contradictory memory? → §2 (consolidate, conflict markers).
3. Turn dropped messages / recursion limit / slow near limit? → §3 (limit-output,
   summarization, subagent).
4. En masse DB errors / no resume? → §4 (docker compose up postgres, verify env).
5. Memory not aging / backlog climb? → §5 (alerts, heartbeat, scan/consolidate).
6. Need perf/isolation evidence? → §6 (load test, observability runbook).
