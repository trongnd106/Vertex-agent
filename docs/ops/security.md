# Security Guide

## Authentication

### API Key Authentication

Set the `AUTH_TOKEN` environment variable to enable API key authentication:

```bash
AUTH_TOKEN="your-secure-api-key" docker compose up agent
```

All requests (except `/health`) must include:

```bash
Authorization: Bearer your-secure-api-key
```

### Generating a Secure Key

```bash
openssl rand -hex 32
```

## CORS

Configure allowed origins via `CORS_ORIGINS`:

```bash
CORS_ORIGINS="https://app.example.com,https://admin.example.com"
```

Default (`*`) allows all origins — restrict in production.

## Sandbox Security

### Container Sandbox

- Commands are wrapped with `timeout` to prevent runaway execution
- Input arguments are `shlex.quote()`-escaped to prevent shell injection
- All commands run inside a Docker container with resource limits
- The sandbox's working directory is isolated from the host

### Local Sandbox (Development Only)

- Enables `LocalShellBackend` with `root_dir` for path isolation
- Path traversal is blocked by `_resolve()` in `FilesystemBackend`
- **Never use in production** — commands run directly on the host

## Database

### Connection Security

- Use `sslmode=require` in `DATABASE_URL` for encrypted connections
- Use separate credentials per environment
- Restrict network access to the PostgreSQL port

### Password Rotation

```bash
# Update password and restart
export DATABASE_URL="postgresql://deepagents:<new-password>@localhost:5432/deepagents"
docker compose up -d agent
```

## Secret Management

### Environment Variables

Sensitive values should be set via environment variables, not config files:

- `AUTH_TOKEN` — API authentication key
- `LANGSMITH_API_KEY` — LangSmith API token
- `OPENAI_API_KEY` — OpenAI API key
- `ANTHROPIC_API_KEY` — Anthropic API key

### Docker Secrets (Recommended for Production)

Use Docker secrets instead of env vars for sensitive data:

```yaml
secrets:
  auth_token:
    file: ./secrets/auth_token.txt

services:
  agent:
    secrets:
      - auth_token
    environment:
      - AUTH_TOKEN_FILE=/run/secrets/auth_token
```