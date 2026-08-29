# deepagents-vertex-agent

Backend agent xây dựng trên **deepagents** (harness agent chính thức của LangChain, chạy trên LangGraph): hệ thống **skill** theo chuẩn `SKILL.md` (progressive disclosure), **tool đầy đủ**, **context management**, **session memory** (checkpointer), **long-term memory** (LangGraph Store + LangMem), và graph **Dreaming** tự cải thiện nền (background self-improvement).

## Bắt đầu

Requires Python **>= 3.11**.

```bash
# Tạo venv (dùng uv cho đơn giản)
uv venv .venv --python 3.11

# Cài dependencies (pinned trong pyproject.toml)
uv pip install --python .venv/bin/python -e ".[dev]"

# Chạy test
.venv/bin/python -m pytest tests/ -v
```

## Khám phá API (Phase 0)

Tài liệu discovery — bản đồ public API của deepagents/langgraph ở chính version đang cài, mọi task sau đều đọc tài liệu này trước khi code:

- [`docs/phase-0-discovery.md`](docs/phase-0-discovery.md)

## Vận hành & Bảo mật

- [`docs/runbook-observability.md`](docs/runbook-observability.md) — LangSmith tracing zero-code (env vars, bật/tắt theo thread, validate thủ công).
- [`docs/tool-audit-checklist.md`](docs/tool-audit-checklist.md) — audit `HarnessProfile`/`excluded_tools` theo role.
- [`docs/phase-0-discovery.md`](docs/phase-0-discovery.md) §16 — FilesystemPermission (`deny`/`interrupt`) và rate limiter.

## Hạ tầng local

Postgres (dùng chung cho checkpointer + Store, bật sẵn pgvector) và Redis (tuỳ chọn) được khai báo trong:

- [`infra/docker-compose.yml`](infra/docker-compose.yml)

```bash
docker compose -f infra/docker-compose.yml up -d
```

## Cấu trúc thư mục

```
├── skills/                  # SKILL.md theo chuẩn Anthropic
├── src/
│   ├── agent/
│   │   ├── tools/           # Custom tool (@tool)
│   │   ├── mcp/             # Cấu hình MCP servers
│   │   └── context/         # Summarization / trim_messages
│   ├── memory/
│   ├── api/
│   └── config/
├── tests/
├── infra/                   # docker-compose
└── docs/                    # phase-0-discovery.md
```
