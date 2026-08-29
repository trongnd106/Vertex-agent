# Runbook — Observability: LangSmith tracing (zero-code)

Repo: deepagents 0.7.9 / langgraph 1.2.11 / langchain-core 1.6.0.

## 1. LangSmith tracing là zero-code (đã verify)

`create_deep_agent` (deepagents) build qua `create_agent`
(`deepagents/graph.py`, dòng compile cuối) thành một LangGraph graph. LangGraph
luôn route execution qua callback manager: `langgraph/pregel/main.py` gọi
`get_callback_manager_for_config(config)` (sync/async) cho từng bước. Hàm đó đi
qua `CallbackManager.configure` (`langchain_core/callbacks/manager.py`), và khi
tracing được bật qua env thì `configure` **tự động** tạo `LangChainTracer` và
gắn vào manager (không cần thêm bất kỳ instrumentation nào trong repo này):

- `langsmith.utils.tracing_is_enabled()` → đọc env (`LANGSMITH_TRACING=true`,
  có fallback `LANGCHAIN_TRACING_V2`).
- `CallbackManager.configure` → `if tracing_v2_enabled_: ... add_handler(LangChainTracer(...))`
  (manager.py ~dòng 2524-2542).
- Tracer đó được kế thừa xuống mọi run con (model call, tool call, node) →
  một `invoke` hoàn chỉnh là một trace với đủ run tree.

Bằng chứng thực nghiệm: chạy agent với fake model + `LANGSMITH_TRACING=true`,
model nhận được `run_manager.handlers` có chứa `LangChainTracer`
(assert trong `tests/test_observability.py` — bản env-gated chỉ chạy khi có
`LANGSMITH_API_KEY`).

> **Giới hạn rõ ràng:** suite CI trong repo này KHÔNG trace được khi không có
> key (deterministic, M1). Test `langsmith` bị skip khi thiếu
> `LANGSMITH_API_KEY`. Việc "trace xuất hiện trên máy chủ LangSmith" là bước
> validate thủ công — xem mục 4.

## 2. Env vars

| Biến | Giá trị | Ý nghĩa |
|---|---|---|
| `LANGSMITH_TRACING` | `true` | Bật tracing (bắt buộc). Chỉ `true` mới bật; unset/rỗng = tắt |
| `LANGSMITH_API_KEY` | key thật | Xác thực với LangSmith; **thiếu key ⇒ không gửi trace lên máy chủ** |
| `LANGSMITH_PROJECT` | tên project | Gộp trace vào project (mặc định `default`) |
| `LANGSMITH_TRACING_SAMPLING_RATE` | 0.0–1.0 | Sample tỷ lệ run được trace (0.5 = nửa số run) |
| `LANGSMITH_TRACING_MODE` | (tuỳ chọn) | `share`/`otel`… xem `langsmith/client.py` |

## 3. Bật/tắt tracing

**Toàn process** — đặt trước khi chạy:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=lsv2_pt_.....
export LANGSMITH_PROJECT=vertex-agent-dev
.venv/bin/python -m pytest tests/test_observability.py -v   # (chạy test `langsmith` thật)
```

> Mẹo cô lập: đặt thêm `LANGSMITH_TEST_TRACKING=false` khi chạy test `langsmith`
> — pytest-langsmith plugin sẽ bỏ dataset/experiment machinery và chỉ giữ đúng
> cơ chế LangChainTracer zero-code (tránh tạo dataset ngẫu nhiên mỗi lần chạy;
> chính plugin này wrap `@pytest.mark.langsmith` qua `langsmith.testing`).

**Tắt:** bỏ/unset `LANGSMITH_TRACING` (hoặc để rỗng, không phải `true`).

**Theo thread/một run** — dùng context manager trong process đang tắt env:

```python
from langchain_core.tracers.context import tracing_v2_enabled
from src.agent.graph import build_agent

agent = build_agent(model="openai:gpt-5.4")  # graph đã compile

with tracing_v2_enabled(project_name="vertex-agent-prod") as cb:
    result = agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
    url = cb.get_run_url()   # lấy thẳng link trace (khi đã có key + nối mạng)
```

`tracing_v2_enabled` đặt `tracing_v2_callback_var`; `configure()` thấy var đó và
gắn tracer đó cho cả cây run dưới nó (`context.py:40`, yields `LangChainTracer`
với `get_run_url()`).

## 4. Validate thủ công (khi có key thật)

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=vertex-agent-manual
.venv/bin/python - <<'EOF'
from deepagents import create_deep_agent

agent = create_deep_agent(model="openai:gpt-5.4")  # model thật; chạy 1 lượt "hello world"
agent.invoke({"messages": [{"role": "user", "content": "Hello!"}]})
EOF
```

Sau đó trên https://smith.langchain.com:

1. Mở project `vertex-agent-manual` (hoặc project trong `LANGSMITH_PROJECT`).
2. Filter theo: thời gian vừa chạy, và/hoặc `metadata.thread_id` /
   `tags` — mỗi `agent.invoke` là một trace gốc; các node/model/tool là run con.
3. Nếu trace rỗng: kiểm tra (a) `LANGSMITH_TRACING=true` đúng, (b) key hợp lệ
   và có quyền ghi project, (c) không có firewall chặn
   `https://api.smith.langchain.com`, (d) `LANGSMITH_TRACING_SAMPLING_RATE` đang
   dưới 1.0.
4. Tương đương trong repo: chạy `test_langsmith_tracer_attached_when_env_enabled`
   với key thật — assert "tracer gắn vào run" đúng nghĩa là cơ chế hoạt động;
   bước 3 ở trên xác nhận data lên máy chủ thật. Đặt `LANGSMITH_TEST_TRACKING=false`
   nếu chỉ muốn kiểm tra cơ chế mà không tạo dataset/experiment.

## 5. Liên hệ bảo mật

- Chỉ gửi trace lên LangSmith khi có chủ đích: `LANGSMITH_TRACING` bật + key thật.
  Bất kỳ prompt/tool result nào cũng là một phần của run — không đặt key trong
  vùng dữ liệu nhạy nếu không đồng ý chia sẻ.
- Env-gated smoke test (`pytest -m langsmith`) không bao giờ chạy trong CI mặc
  định vì thiếu key; đừng fake key trong CI.