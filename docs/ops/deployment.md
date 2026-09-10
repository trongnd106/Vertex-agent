# Deployment Guide

## Prerequisites

- Python 3.11+
- Docker & Docker Compose v2
- PostgreSQL 16 (or pgvector/pgvector:pg16 via Docker)
- Redis 7 (optional, for session backend)
- OpenAI API key (or other LLM provider key)

## Quick Start (Development)

```bash
# 1. Clone and install
git clone <repo>
cd vertex-agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Start infrastructure
docker compose -f infra/docker-compose.yml up postgres -d

# 3. Run agent
AGENT_MODEL="openai:gpt-4o-mini" \
  langgraph dev --host 0.0.0.0 --port 8000
```

## Production Deployment

### Using Docker Compose

```bash
# Start all services with production profile
docker compose -f infra/docker-compose.yml \
  --profile production up -d

# Check status
docker compose ps
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_MODEL` | `openai:gpt-4o-mini` | Provider:model for the agent |
| `DATABASE_URL` | `postgresql://deepagents:deepagents@localhost:5432/deepagents` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `LANGSMITH_TRACING` | `false` | Enable LangSmith tracing |
| `LANGSMITH_API_KEY` | — | LangSmith API key (required if tracing enabled) |
| `AUTH_TOKEN` | — | API key for request authentication |
| `CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |
| `SERVER_HOST` | `0.0.0.0` | FastAPI server bind address |
| `SERVER_PORT` | `8000` | FastAPI server port |

### Configuration Files

Environment-specific configs are in `config/`:

- `config/dev.yml` — Development settings
- `config/staging.yml` — Staging/pre-production settings
- `config/production.yml` — Production settings

Select via the `APP_ENV` environment variable (default: `dev`).

## Health Check

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.4.0","uptime_seconds":123.4,"total_requests":42,"graph_loaded":true}
```

## Metrics

```bash
curl http://localhost:8000/metrics
# {"uptime_seconds":123.4,"total_requests":42}
```