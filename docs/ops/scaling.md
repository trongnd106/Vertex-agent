# Scaling Guide

## Horizontal Scaling

### API Layer

The FastAPI server is stateless (state is in PostgreSQL/Redis). Scale by running multiple instances:

```bash
# Start additional instances on different ports
SERVER_PORT=8001 langgraph serve --host 0.0.0.0 --port 8001
SERVER_PORT=8002 langgraph serve --host 0.0.0.0 --port 8002
```

Place a reverse proxy (nginx, HAProxy, or a cloud LB) in front:

```nginx
upstream agent_backend {
    server localhost:8000;
    server localhost:8001;
    server localhost:8002;
}

server {
    listen 80;
    location / {
        proxy_pass http://agent_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Docker Compose Scaling

```bash
docker compose up -d --scale agent=3 agent
```

**Note:** When scaling via Docker Compose, ensure the `postgres` service is healthy before the agent instances start.

## Resource Sizing

| Environment | CPU | Memory | Replicas | Storage |
|-------------|-----|--------|----------|---------|
| Development | 1 | 512MB | 1 | 10GB |
| Staging | 2 | 1GB | 1-2 | 20GB |
| Production | 4+ | 2GB+ | 2-5 | 50GB+ |

## Database Scaling

- **Read replicas:** Use PostgreSQL read replicas for state queries (GET /state)
- **Connection pooling:** Use PgBouncer for high-connection environments
- **Migration strategy:** Zero-downtime via `MigrationManager.is_idempotent()` — migrations apply only if not yet run

## Session Backend

For high-throughput deployments:

1. **Redis cluster** — Enable `RedisSessionBackend` with a cluster connection
2. **Database session** — Use `DatabaseSessionBackend` with proper indexing
3. **In-memory only** — Acceptable for single-instance dev; data lost on restart

## Rate Limiting

The token-bucket `RateLimiter` (60 req/s burst, 1 req/s sustained) is tuned for a single instance.
In a multi-instance deployment, consider a distributed rate limiter (Redis-based) to share state across instances.