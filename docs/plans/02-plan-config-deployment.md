# Plan 02 — Config tập trung + Deployment stack đầy đủ

## Mục tiêu

Gom toàn bộ hằng số/biến môi trường rải rác hiện nay thành 1 nguồn sự thật
duy nhất, và làm cho `docker compose up` khởi động được **toàn bộ** hệ thống
(DB + agent server), không chỉ mỗi Postgres như hiện tại.

---

## Task A — `src/config/settings.py`: Settings tập trung

**Hiện trạng cần dọn** (liệt kê để không sót khi refactor):

| Hằng số hiện tại | File | Nên chuyển vào Settings field |
|---|---|---|
| `AGENT_MODEL` / `DEFAULT_MODEL` | `src/agent/server.py` | `settings.agent_model` |
| `DATABASE_URL` (đọc trực tiếp `os.environ` ở 4+ nơi) | `checkpointer.py`, `store.py`, `cleanup.py`, `load_test.py` | `settings.database_url` |
| `DEFAULT_MAX_AGE_DAYS = 30` | `src/memory/cleanup.py` | `settings.stale_thread_max_age_days` |
| `DEFAULT_MAX_AGE_SECONDS = 3600`, `DEFAULT_MAX_BACKLOG = 50` | `src/memory/dreaming/alerts.py` | `settings.dreaming_heartbeat_max_age_seconds`, `settings.dreaming_max_backlog` |
| `DEFAULT_TRIGGER`, `DEFAULT_KEEP` | `src/agent/context/summarization.py` | `settings.summarization_trigger_tokens`, `settings.summarization_keep_messages` |
| `DEFAULT_MAX_LENGTH = 4000` | `src/agent/context/limit_output.py` | `settings.tool_output_max_length` |
| `_DEFAULT_TIMEOUT_SECONDS = 30` | `src/agent/tools/sandbox.py` | `settings.sandbox_default_timeout_seconds` |
| capacity/refill_rate mặc định | CLI args trong `rate_limit.py` (đã tốt, giữ CLI override) | `settings.rate_limit_capacity`, `settings.rate_limit_refill_rate` |
| `TAVILY_API_KEY` (mới, từ plan 01) | — | `settings.tavily_api_key` |

**Thiết kế:**

```python
# src/config/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Model
    agent_model: str = "openai:gpt-4o-mini"

    # Database
    database_url: str | None = None

    # Session cleanup
    stale_thread_max_age_days: int = 30

    # Dreaming
    dreaming_heartbeat_max_age_seconds: int = 3600
    dreaming_max_backlog: int = 50
    dreaming_stale_after_days: int = 30

    # Context management
    summarization_trigger_tokens: int = 20000
    summarization_keep_messages: int = 6
    tool_output_max_length: int = 4000

    # Sandbox
    sandbox_default_timeout_seconds: int = 30

    # Rate limiting
    rate_limit_capacity: float = 5.0
    rate_limit_refill_rate: float = 1.0

    # Optional tools
    tavily_api_key: str | None = None

    # Observability
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "vertex-agent"


def get_settings() -> Settings:
    return Settings()
```

**Nguyên tắc migrate (quan trọng — không phá test hiện có):**

- Mỗi module giữ nguyên tham số hàm/CLI arg như cũ (`get_checkpointer(url)`,
  `cleanup_stale_threads(..., max_age_days=...)`, CLI `--max-age-days`...) —
  **không đổi public API**. Settings chỉ thay đổi **giá trị mặc định** khi gọi
  không truyền tham số (`arg or get_settings().field`), và là nguồn cho
  `server.py`/CLI entrypoints khi build từ đầu.
- Việc này giữ 100% test hiện có (chúng gọi function trực tiếp với tham số
  tường minh, không phụ thuộc Settings) trong khi vẫn tập trung hoá default.
- `tests/test_config.py` mới: test Settings đọc đúng từ env var, test default
  values khớp với các `DEFAULT_*` hiện tại (không silently đổi hành vi).

**Không đưa vào Settings:** secrets thật (API key) không nên có default —
field `| None = None`, và mọi nơi dùng phải tự xử lý "thiếu key thì làm gì"
(ví dụ Task B ở plan 01: không add web_search tool nếu thiếu key).

---

## Task B — `.env.example`

Tạo file liệt kê **mọi** biến môi trường thực repo cần, kèm comment ngắn:

```
# Model provider (bắt buộc để chạy thật; test dùng fake model, không cần)
AGENT_MODEL=openai:gpt-4o-mini
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Database (bỏ trống -> dev fallback MemorySaver/InMemoryStore)
DATABASE_URL=postgresql://deepagents:deepagents@localhost:5432/deepagents

# Observability (tuỳ chọn)
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=vertex-agent-dev

# Web search tool (tuỳ chọn — thiếu thì tool không được add vào agent)
TAVILY_API_KEY=

# Dreaming ops (tuỳ chọn, có default hợp lý)
DREAMING_HEARTBEAT_MAX_AGE_SECONDS=3600
DREAMING_MAX_BACKLOG=50
```

`.gitignore` đã có `.env` — chỉ cần thêm `.env.example` (KHÔNG gitignore).

---

## Task C — `docker-compose.yml` full stack

Mở rộng `infra/docker-compose.yml` hiện tại (chỉ có `postgres`) thêm service
`agent`:

```yaml
services:
  postgres:
    # ... (giữ nguyên như hiện tại)

  agent:
    build:
      context: ..
      dockerfile: Dockerfile
    env_file:
      - ../.env
    environment:
      DATABASE_URL: postgresql://deepagents:deepagents@postgres:5432/deepagents
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8123:8123"   # cổng mặc định LangGraph API server
```

Lưu ý cần verify khi triển khai (KHÔNG giả định, phải chạy thật để xác nhận
giống cách discovery doc đã làm cho mọi API khác trong repo này):

- Cổng thật mà `langgraph-api` image lắng nghe (kiểm tra qua
  `langgraph up --help` hoặc chạy thử — đừng copy `8123` mù quáng).
- Biến `LANGGRAPH_CHECKPOINTER`/`LANGGRAPH_STORE` set trong `Dockerfile` đã
  cố định `"postgres"` — cần đảm bảo `DATABASE_URL` trong container trỏ đúng
  hostname service (`postgres`, không phải `localhost`).

**Test:** `docker compose -f infra/docker-compose.yml up -d`, sau đó 1 script
smoke-test gọi HTTP endpoint của agent server (không có sẵn trong repo hiện
tại vì Ruling M4 cấm dựng API Gateway — script này chỉ gọi thẳng LangGraph API
server có sẵn, không phải viết thêm gateway).

---

## Task D — CI tối thiểu (GitHub Actions hoặc tương đương)

`\.github/workflows/ci.yml`:

1. `uv pip install -e ".[dev]"`.
2. `docker compose -f infra/docker-compose.yml up -d postgres` (cho các test
   `@skip_postgres` chạy thật thay vì skip).
3. `pytest tests/ -v` (không set `LANGSMITH_API_KEY` → test `langsmith` tự
   skip đúng như thiết kế hiện tại).
4. `langgraph validate`.
5. (Tuỳ chọn) `langgraph build -t vertex-agent:ci` để bắt sớm lỗi Dockerfile
   drift nếu ai đó sửa `langgraph.json` mà quên sinh lại Dockerfile.

Không cần bước deploy thật trong phạm vi plan này — dừng ở "build + test xanh
trên mỗi PR".
