# Plan 03 — Ráp lại Context/Memory Middleware vào `build_agent` + Scalability + Scheduler

> Đây là plan **ưu tiên cao nhất**: sửa một lỗ hổng nối dây (integration bug),
> không phải build tính năng mới. Rủi ro nếu bỏ qua: agent chạy production
> qua `src/agent/server.py:graph` KHÔNG có context management thật sự dù mọi
> mảnh ghép đã viết và test xong ở cấp module.

## Task A — Thêm `middleware: list = ()` mở rộng vào `build_agent`

**Vấn đề hiện tại:** `build_agent()` (`src/agent/graph.py`) tự xây `middleware`
list nội bộ (chỉ có `EnqueueAfterTurnMiddleware` khi truyền `enqueue`), và
truyền thẳng vào `create_deep_agent(middleware=middleware or None)`. Không có
cách nào cho caller thêm middleware khác mà không sửa source.

**Sửa (giữ tương thích ngược 100% — không đổi signature hiện có, chỉ thêm
tham số mới có default rỗng):**

```python
def build_agent(
    *,
    model: str | BaseChatModel,
    store: BaseStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    system_prompt: str | None = None,
    skills: Sequence[str] = ("/skills/",),
    backend: BackendProtocol | None = None,
    tools: Sequence[BaseTool] = DEFAULT_TOOLS,
    context_schema: type[Any] = DEFAULT_CONTEXT_SCHEMA,
    enqueue: Callable[[str, str], None] | None = None,
    subagents: Sequence[Any] | None = None,          # MỚI
    middleware: Sequence[Any] = (),                   # MỚI — mở rộng tự do
    enable_default_context_management: bool = True,   # MỚI — xem Task B
) -> CompiledStateGraph:
    ...
    built_middleware: list[Any] = list(middleware)
    if enqueue is not None:
        built_middleware.append(EnqueueAfterTurnMiddleware(enqueue))
    if enable_default_context_management:
        built_middleware = _default_context_middleware(model) + built_middleware
    return create_deep_agent(
        ...,
        subagents=list(subagents) if subagents else None,
        middleware=built_middleware or None,
    )
```

- `middleware` mới cho phép bất kỳ caller nào (test, deployment khác, plugin
  tương lai) thêm middleware **không cần sửa `graph.py`** — giải quyết đúng
  câu hỏi "có dễ dàng scalable không" trong yêu cầu gốc.
- Thứ tự middleware: `_default_context_middleware` (summarization + limiter,
  xem Task B) đặt **trước** middleware do caller truyền, để caller có thể
  override theo đúng semantics "replace-by-name" đã verify ở
  `docs/phase-0-discovery.md` §12.8 (nếu caller truyền 1
  `SummarizationMiddleware` khác, nó sẽ thay thế cái mặc định, không stack).

**Test cần thêm** (`tests/test_context.py`, bổ sung, không sửa test cũ):

- `build_agent(model=..., middleware=[CustomProbeMiddleware()])` → middleware
  custom thực sự chạy (dùng fake middleware đếm số lần gọi `after_agent`).
- `build_agent(model=..., enable_default_context_management=True)` (default)
  → xác nhận `LimitToolOutputMiddleware` VÀ summarization tuỳ chỉnh đều có
  mặt trong graph đã compile (kiểm tra qua behavior giống
  `test_tool_output_limiter_truncates_oversized_result` nhưng gọi qua
  `build_agent` thay vì `create_deep_agent` trực tiếp — đây chính là test còn
  thiếu hiện nay, vì `tests/test_context.py` hiện tại chỉ test module rời).

---

## Task B — Wire mặc định: summarization + limit-output + research subagent

**`_default_context_middleware(model)` helper** (đặt trong `graph.py` hoặc
tách `src/agent/context/__init__.py`):

```python
def _default_context_middleware(model: str | BaseChatModel) -> list[Any]:
    resolved = _resolve_model_for_summarization(model)  # xử lý cả string spec
    return [
        build_summarization_middleware(resolved),   # đã có, chỉ cần GỌI
        LimitToolOutputMiddleware(),                  # đã có, chỉ cần GỌI
    ]
```

**Research subagent mặc định:** thêm `RESEARCH_SUBAGENT` vào `subagents` mặc
định của `build_agent` khi caller không tự truyền:

```python
def build_agent(..., subagents: Sequence[Any] | None = None, ...):
    resolved_subagents = list(subagents) if subagents is not None else [
        build_research_subagent()
    ]
```

**Điểm cần cẩn trọng (đã ghi nhận trong discovery §12.10):**
`resolve_model` trả **cùng instance** khi `model` là `BaseChatModel` — nghĩa
là subagent sẽ dùng chung fake model với main agent trong test (đã biết, đã
xử lý qua system-prompt marker ở `tests/test_context.py`). Khi wire vào
`build_agent`, giữ nguyên hành vi này — không tự ý build model riêng cho
subagent trừ khi có yêu cầu cụ thể (tránh side-effect ngoài phạm vi).

**`enable_default_context_management=True` làm default** để không phá vỡ kỳ
vọng — nhưng cho phép `False` (ví dụ `tests/test_context.py` hiện tại vẫn gọi
`create_deep_agent` trực tiếp, không bị ảnh hưởng; các test khác dùng
`build_agent` với model fake nhỏ có thể tắt nếu summarization mặc định gây
nhiễu số message trong assertion — audit lại từng test khi migrate).

**Việc BẮT BUỘC phải làm khi migrate:** chạy lại toàn bộ
`tests/test_hello_world.py`, `tests/test_session_memory.py`,
`tests/test_long_term_memory.py`, `tests/test_dreaming.py`,
`tests/test_load_test.py` sau khi bật default context management — các test
này dùng `build_agent` với hội thoại rất ngắn (2-5 message), nên ngưỡng
summarization mặc định (`("tokens", 20000)`) không nên fire, nhưng phải
**verify thật bằng cách chạy**, không giả định.

---

## Task C — `enqueue` mặc định trong `server.py` (tự động hoá Dreaming trigger)

**Vấn đề:** `src/agent/server.py::_build_graph()` gọi `build_agent(model=...)`
không truyền `enqueue` → production graph không bao giờ enqueue thread nào
cho Dreaming.

**Sửa** (`src/agent/server.py`):

```python
def _default_enqueue() -> Callable[[str, str], None] | None:
    """Simple durable enqueue: append (thread_id, user_id) to a Store namespace
    the cold-scan can read, since no broker exists (ruling M4/M6 giữ nguyên)."""
    from src.memory.store import get_store

    store = get_store()  # cùng DATABASE_URL convention hiện có

    def _enqueue(thread_id: str, user_id: str) -> None:
        store.put(("system", "dream_queue"), thread_id, {"user_id": user_id})

    return _enqueue


def _build_graph():
    return build_agent(model=_model_from_env(), enqueue=_default_enqueue())
```

- Đây là 1 hàng đợi **durable nhưng đơn giản** (Store-backed), phù hợp với
  ruling hiện có trong repo ("no Celery/BullMQ", §15 discovery) — không vi
  phạm scope đã chốt, chỉ hoàn thiện phần chưa nối dây.
- `python -m src.memory.dreaming.scan` cần thêm chế độ đọc từ
  `("system", "dream_queue")` thay vì chỉ nhận `--user` bắt buộc (hiện tại
  scan.py yêu cầu `--user` vì "thread_id không map ngược ra user được" — với
  enqueue mới, `user_id` đã có sẵn trong item, giải quyết đúng limitation đã
  ghi nhận trong `scan.py` docstring).

**Test:** `tests/test_dreaming.py` bổ sung — `build_agent(...,
enqueue=_default_enqueue())` sau 1 turn → item xuất hiện đúng trong
`("system", "dream_queue")`; `scan.py` (bản mở rộng) đọc lại đúng cặp
`(thread_id, user_id)` và dream đúng thread đó.

---

## Task D — Scheduler tối thiểu cho Dreaming (cron, không phải broker)

**Phạm vi cố ý nhỏ** (không vi phạm ruling "no Celery/BullMQ" đã có trong
repo — chỉ thêm 1 entrypoint có thể lên lịch bằng cron/K8s CronJob, không tự
viết job queue):

`src/memory/dreaming/run_once.py` — 1 script tổng hợp gọi tuần tự:

1. Đọc `("system", "dream_queue")`, dream từng `(thread_id, user_id)`, xoá
   khỏi queue sau khi dream xong (dùng `store.delete`).
2. Chạy `run_consolidation` cho mọi user vừa dream.
3. Ghi heartbeat (`alerts.write_heartbeat`).
4. Exit code 0 nếu không lỗi, khớp pattern các CLI khác trong repo.

Deploy: `* * * * * python -m src.memory.dreaming.run_once` (cron) hoặc K8s
CronJob mỗi 1-5 phút — tài liệu hoá trong `docs/runbook-operations.md` §5
(cập nhật mục "Kicking a stalled pipeline" để trỏ vào `run_once.py` thay vì
yêu cầu operator tự gõ `scan` rồi `consolidate` tay).

**Test:** `tests/test_dreaming.py` — deterministic, dùng `InMemoryStore` +
`MemorySaver`, giả lập 1 turn thật (enqueue), gọi `run_once.main()`, assert
queue rỗng sau khi chạy + facts/lessons đã ghi + heartbeat tồn tại.

---

## Tóm tắt thứ tự triển khai (mỗi bước độc lập, có thể merge riêng)

1. Task A (thêm tham số `middleware`/`subagents` — an toàn, không đổi hành vi
   mặc định nếu `enable_default_context_management=False` tạm thời).
2. Task B (bật default context management — **chạy lại toàn bộ test suite**
   trước khi merge, vì đây là thay đổi hành vi mặc định thật sự).
3. Task C (enqueue mặc định trong `server.py` + mở rộng `scan.py`).
4. Task D (scheduler script + cập nhật runbook).
