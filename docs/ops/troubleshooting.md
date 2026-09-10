# Troubleshooting Guide

## Common Issues

### 1. Agent returns 503 Service Unavailable

**Cause:** Agent graph failed to load at startup.

**Check:**
```bash
# Inspect container logs
docker compose logs agent | grep -i error

# Verify the module can import
python -c "from src.agent.server import graph; print('OK')"
```

**Fix:** Ensure `AGENT_MODEL` env var is set and the LLM provider key is configured.

### 2. Database connection failures

**Cause:** PostgreSQL not running or connection string misconfigured.

**Check:**
```bash
# Test connectivity
psql "$DATABASE_URL" -c "SELECT 1"

# Verify container status
docker compose ps postgres
```

**Fix:**
```bash
docker compose up -d postgres
# Wait for health check to pass
docker compose wait postgres
```

### 3. Docker healthcheck failing

**Cause:** Agent process not responding within timeout.

**Check:**
```bash
docker inspect --format='{{json .State.Health}}' <container>
```

**Fix:** Increase timeout or check resource limits. Agent may need more memory.

### 4. LangSmith API errors

**Cause:** `LANGSMITH_TRACING=true` but `LANGSMITH_API_KEY` not set.

**Fix:**
```bash
export LANGSMITH_TRACING=false  # disable tracing
# OR
export LANGSMITH_API_KEY="your-key-here"
```

### 5. "No module named 'langchain_core'"

**Cause:** Dependencies not installed.

**Fix:**
```bash
pip install -e ".[dev]"
```

## Debugging Checklist

1. **Configuration** — Run `python -c "from src.backends.config import create_default_config; print('OK')"` to verify config module loads
2. **Database** — Check `DATABASE_URL` env var and PostgreSQL connectivity
3. **API Auth** — If `AUTH_TOKEN` is set, ensure all requests include `Authorization: Bearer <token>` header
4. **CORS** — If making cross-origin requests, verify `CORS_ORIGINS` includes the origin
5. **Resource limits** — Docker containers may restart under memory pressure; check `docker compose logs` for OOM

## Getting Help

- Check the [Deployment Guide](deployment.md) for configuration reference
- Review [Monitoring Guide](monitoring.md) for health check details
- See [Backup & Restore](backup-restore.md) for data recovery procedures