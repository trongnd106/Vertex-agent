# Monitoring Guide

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check with graph status |
| `/metrics` | GET | Runtime metrics (uptime, request count) |

## Logging

Logs are output via Python's `logging` module at `INFO` level by default.
Set `LOG_LEVEL` environment variable to override:

```bash
LOG_LEVEL=DEBUG langgraph serve --host 0.0.0.0 --port 8000
```

### Docker Logs

```bash
# Follow agent logs
docker compose logs -f agent

# Last 100 lines with timestamps
docker compose logs --tail=100 -t agent
```

## Prometheus / Grafana (Coming Soon)

The `/metrics` endpoint is designed to be scraped by Prometheus.
Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'vertex-agent'
    static_configs:
      - targets: ['localhost:8000']
```

## Alerting Rules (Recommended)

| Condition | Severity | Action |
|-----------|----------|--------|
| `/health` returns `degraded` for >30s | Warning | Restart agent container |
| Request latency p95 > 5s | Warning | Scale up or investigate bottlenecks |
| Error rate > 5% over 5m | Critical | Check logs and rollback if needed |
| Database connection lost | Critical | Check PostgreSQL health |

## Docker Healthcheck

The agent container includes a built-in healthcheck that curls `/health` every 30s:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

View health status:

```bash
docker compose ps
# Look for "healthy" / "unhealthy" under STATUS
```