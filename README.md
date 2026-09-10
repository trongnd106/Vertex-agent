# Vertex Agent

Backend AI agent xây dựng trên **deepagents** — harness chính thức của LangChain chạy trên **LangGraph**. Hệ thống tích hợp skill chuẩn `SKILL.md` (progressive disclosure), bộ tool phong phú, quản lý context, session & long-term memory, và graph **Dreaming** tự cải thiện nền (background self-improvement).

## Đặc điểm nổi bật

- **Skills theo chuẩn `SKILL.md`** — hơn 30 skill đóng gói sẵn, agent tự index và lựa chọn skill phù hợp theo từng yêu cầu.
- **Memory hai tầng**:
  - *Session memory* — checkpointer Postgres (`langgraph-checkpoint-postgres`) cho hội thoại multi-turn.
  - *Long-term memory* — LangGraph Store kết hợp **LangMem**, lưu theo namespace người dùng (`("memories", user_id)`) với context schema riêng biệt.
- **Dreaming** — graph nền chạy ngầm, thu thập và củng cố ký ức định kỳ để cải thiện chất lượng trả lời qua thời gian.
- **Tích hợp tool linh hoạt** — custom tools (`@tool`), MCP servers, filesystem backend, sandbox execution.
- **Quản lý context** — summarization, trim messages, giới hạn output.
- **Đa nền tảng LLM** — OpenRouter, OpenAI, LiteLLM, Gemini, Anthropic (đổi qua biến môi trường, không đổi code).
- **API server đầy đủ** — invoke đồng bộ, streaming (SSE), thao tác thread state, health check, runtime metrics.
- **Middleware mở rộng** — security, tool injection, summarization, progress, rubric, audit.
- **Routing & HITL** — workflow có điều kiện, loop, human-in-the-loop (interrupt/resume).
- **Subagents** — chạy song song/bất đồng bộ, giao tiếp giữa các subagent.
- **RAG & Research** — knowledge base (vector store + pgvector), agent nghiên cứu (search → read → synthesize).

## Kiến trúc

```
┌──────────────────────────────────────────────────────────────┐
│                    Client / Integration Layer               │
│        FastAPI (/invoke, /stream, /state, /health)          │
│        LangGraph API Server (/assistant, /memory, /skills)  │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                      Agent Graph (LangGraph)                 │
│   deepagents harness  ·  skills middleware · subagents      │
│   routing (HITL/workflow)  ·  streaming (SSE) · middleware  │
└───────┬──────────────────────────────┬──────────────────────┘
        │                              │
┌───────▼───────────┐   ┌──────────────▼───────────────────────┐
│  Session Memory   │   │  Long-term Memory & Knowledge        │
│  Checkpointer     │   │  LangGraph Store · LangMem           │
│  (Postgres)       │   │  RAG / Vector Store (pgvector)       │
└───────────────────┘   │  Dreaming (self-improvement)         │
                        └──────────────────────────────────────┘
```

## Bắt đầu nhanh

Yêu cầu **Python >= 3.11**. Khuyến nghị dùng [uv](https://docs.astral.sh/uv/).

```bash
# Tạo môi trường ảo
uv venv .venv --python 3.11

# Cài dependencies (đã pin trong pyproject.toml)
uv pip install --python .venv/bin/python -e ".[dev]"

# Cấu hình biến môi trường
cp .env.example .env   # sau đó điền API key và cấu hình LLM

# Chạy test
.venv/bin/python -m pytest tests/ -v
```

## Cấu hình

Tất cả cấu hình qua biến môi trường (xem `.env.example`). Bảng chính:

| Biến | Mô tả | Mặc định |
| --- | --- | --- |
| `LLM_PROVIDER` | Nhà cung cấp LLM: `OpenRouter` / `OpenAI` / `LiteLLM` / `Gemini` | `LiteLLM` |
| `LLM_MODEL` / `AGENT_MODEL` | Tên model (ví dụ `deepseek-v4-flash`, `gpt-4o`) | — |
| `DATABASE_URL` | Postgres cho checkpointer + Store (pgvector) | `postgresql://deepagents:deepagents@localhost:5432/deepagents` |
| `REDIS_URL` | Redis (tuỳ chọn) | `redis://localhost:6379/0` |
| `AUTH_TOKEN` | Bearer token cho API (bỏ trống = không xác thực) | — |
| `LANGSMITH_TRACING` | Bật tắt LangSmith tracing | `false` |
| `SANDBOX_TYPE` | Chế độ thực thi sandbox: `local` | `local` |
| `DREAMING_ENABLED` | Bật tắt graph Dreaming nền | `true` |
| `DREAMING_INTERVAL_SECONDS` | Chu kỳ củng cố ký ức | `300` |

Ngoài ra, cấu hình triển khai theo môi trường trong `config/` (`dev.yml`, `staging.yml`, `production.yml`) với các class middleware riêng biệt.

## Hạ tầng local

Postgres (dùng chung cho checkpointer + Store, bật sẵn pgvector) và Redis được khai báo trong `infra/docker-compose.yml`:

```bash
docker compose -f infra/docker-compose.yml up -d
```

## Chạy server

### LangGraph API server (khuyến nghị)

```bash
.venv/bin/python -m langgraph serve --port 8000
```

Server mở tại `http://localhost:8000` với các route `/assistant`, `/memory`, `/skills` và Swagger UI tự động.

### FastAPI server

```bash
.venv/bin/python -m src.api.server
```

## API Endpoints

| Method | Đường dẫn | Mô tả |
| --- | --- | --- |
| `GET` | `/health` | Kiểm tra sức khỏe, uptime, số request |
| `GET` | `/metrics` | Runtime metrics |
| `POST` | `/invoke` | Gọi agent đồng bộ, trả về câu trả lời đầy đủ |
| `POST` | `/stream` | Streaming response (SSE) |
| `GET` | `/state/{thread_id}` | Lấy trạng thái checkpoint của thread |
| `POST` | `/state/{thread_id}` | Cập nhật trạng thái thread (resume sau interrupt) |

Ví dụ gọi `/invoke`:

```bash
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u-1", "message": "Tra cứu đơn hàng A-1001"}'
```

Mỗi request hỗ trợ `user_id` — agent sẽ tự lưu ký ức vào namespace riêng của người dùng đó.

## Triển khai với Docker

Build image multi-stage và chạy stack đầy đủ (Postgres + Redis + agent):

```bash
docker compose -f infra/docker-compose.yml --profile production up -d --build
```

```bash
# Build image thủ công
docker build -t vertex-agent .

# Chạy với biến môi trường
docker run -p 8000:8000 --env-file .env vertex-agent
```

## Cấu trúc thư mục

```
├── skills/                  # Bộ skill theo chuẩn SKILL.md
├── src/
│   ├── agent/               # deepagents harness, system prompt, tool, MCP, context
│   ├── memory/              # Checkpointer, Store, long-term memory, Dreaming
│   ├── api/                 # FastAPI server, rate limiting
│   ├── graph/               # Graph builder, channels, reducers, runtime
│   ├── backends/            # Filesystem / sandbox backends, database
│   ├── routing/             # Conditional workflow, loops, HITL
│   ├── subagents/           # Parallel / async subagents, communication
│   ├── streaming/           # SSE gateway, transport, formatters
│   ├── knowledge/           # RAG, vector store
│   ├── research/            # Research agent (search → read → synthesize)
│   ├── multimodal/          # Image, video, code execution
│   ├── middleware/          # Security, summarization, progress, rubric, audit
│   └── extensions/          # Plugin & hooks
├── config/                  # Cấu hình dev / staging / production
├── infra/                   # Docker Compose, Dockerfile
└── tests/                   # Bộ test đầy đủ (mô phỏng + thực)
```

## Phát triển & Kiểm thử

- Bộ test chạy độc lập với LLM thật nhờ fake model (`tests/fake_model.py`) — phù hợp CI.
- Kiểm thử tích hợp với model thật đánh dấu bằng marker `langsmith` (cần `LANGSMITH_API_KEY`):

```bash
.venv/bin/python -m pytest tests/ -m "not langsmith" -v
```