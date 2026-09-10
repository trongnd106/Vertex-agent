# Deployment & Operations

> **Nguồn tham khảo:** LangGraph CLI (`langgraph-cli`), `langgraph.json` config; Vertex-agent `Dockerfile`, `src/agent/server.py`, `infra/docker-compose.yml`; orchestrator `orchestrator.py` (FastAPI server)

## Mục tiêu

Xây dựng deployment và operations: Docker containerization, LangGraph server, load testing, monitoring, và runbook.

## Tasks

### Task 9.1: LangGraph Server Setup

**Mô tả:** Setup LangGraph API server cho production deployment.

**File tham khảo:**
- Vertex-agent: `src/agent/server.py` (server module, module-level graph)
- `langgraph.json` (graphs, dependencies, checkpointer)
- LangGraph CLI: `langgraph dockerfile`, `langgraph build`, `langgraph up`

**Yêu cầu:**
- Server module: `src/agent/server.py` với module-level compiled graph
- `langgraph.json`:
  - `graphs`: `{"agent": "./src/agent/server.py:graph"}`
  - `dependencies`: `["."]`
  - `checkpointer`: `"postgres"`
  - `store`: index disabled (không cần embedding key)
  - `env`: `AGENT_MODEL`, etc.
- Server thin wrapper: không double-manage store/checkpointer
- Environment-based model configuration: `AGENT_MODEL` env var
- Multiple deployment targets: dev, staging, production

### Task 9.2: Docker & Containerization

**Mô tả:** Setup Docker containerization cho agent deployment.

**File tham khảo:**
- LangGraph CLI: `langgraph dockerfile` (Dockerfile generation)
- `langgraph build` (image building)
- Vertex-agent: `infra/docker-compose.yml`

**Yêu cầu:**
- Dockerfile generation: `langgraph dockerfile ./Dockerfile`
- Base image: `langchain/langgraph-api:3.11`
- Multi-stage build: dependencies -> source -> runtime
- Docker compose:
  - Agent service
  - Postgres service (checkpointer + store)
  - Redis service (optional, session state)
  - Environment variables
- Image tagging: version-tagged images
- Health checks: service health endpoints
- Resource limits: CPU, memory per container

### Task 9.3: API Layer & Gateway

**Mô tả:** Xây dựng API layer cho agent communication.

**File tham khảo:**
- orchestrator: `orchestrator.py` (FastAPI server, endpoints)
- Vertex-agent: `src/api/` (load_test.py, rate_limit.py)

**Yêu cầu:**
- FastAPI server with endpoints:
  - `POST /invoke` — invoke agent (sync)
  - `POST /stream` — invoke agent (stream response)
  - `GET /state/{thread_id}` — get thread state
  - `POST /state/{thread_id}` — update thread state
  - `GET /health` — health check
  - `GET /metrics` — metrics endpoint
- Rate limiting: token bucket per user
- Request validation: Pydantic models
- Authentication: API key / JWT
- CORS: configurable CORS policy
- Error responses: standardized error format

### Task 9.4: Load Testing & Benchmarking

**Mô tả:** Implement load testing và benchmarking tools.

**File tham khảo:**
- Vertex-agent: `src/api/load_test.py` (run_concurrent_sessions)
- `tests/test_load_test.py`
- LangGraph: benchmark tools

**Yêu cầu:**
- Concurrent session execution:
  - N thread_id song song qua ThreadPoolExecutor
  - Shared PostgresSaver + PostgresStore
  - Assert isolation: mỗi session đúng fact của mình
  - Throughput REPORT: sessions/s, invokes/s
- Load test scenarios:
  - Single user, multiple turns
  - Multiple concurrent users
  - Long conversation (many turns)
  - Tool-heavy workload
- Benchmark metrics:
  - Response time (p50, p95, p99)
  - Throughput (requests/second)
  - Token usage per request
  - Error rate
- CI integration: load test là một phần của CI pipeline

### Task 9.5: Operations Runbook

**Mô tả:** Tạo operations runbook cho production deployment.

**File tham khảo:**
- Vertex-agent: `docs/runbook-observability.md`, `docs/runbook-operations.md`
- orchestrator: observability patterns

**Yêu cầu:**
- Deployment guide:
  - Prerequisites (Python, Postgres, Redis)
  - Environment setup
  - Configuration
  - Start/stop services
- Monitoring guide:
  - LangSmith tracing setup
  - Key metrics to watch
  - Alert thresholds
  - Dashboard setup
- Troubleshooting guide:
  - Common issues and solutions
  - Debug mode
  - Log analysis
- Backup/restore:
  - Database backup
  - Configuration backup
  - Recovery procedure
- Scaling guide:
  - Horizontal scaling
  - Connection pooling
  - Caching strategy
- Security guide:
  - API key management
  - Network security
  - Data encryption