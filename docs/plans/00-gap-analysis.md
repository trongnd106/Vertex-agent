# Gap Analysis — deepagents-vertex-agent

> Đối chiếu trực tiếp với code/test/docs hiện có trong repo (không suy diễn thêm
> tính năng). Mục tiêu: xác định chính xác cái gì ĐÃ xong, ĐÃ test, và cái gì
> CHƯA có, để 3 file plan còn lại (01/02/03) giải quyết đúng phần thiếu.

## 1. Đã có, đã test tốt (giữ nguyên, không động vào)

- `create_deep_agent` wiring cơ bản: skills (`skills/*`), built-in fs tools,
  checkpointer (Memory/Postgres), Store (InMemory/Postgres), permissions
  (`FilesystemPermission`), role-based tool exclusion (`HarnessProfile`).
- Session memory (Phase 4) + Long-term memory (Phase 5) qua Store, đã verify
  cross-thread / cross-process / multi-user isolation.
- Dreaming graph (Phase 6): dream/consolidate/scan/alerts — logic đúng, có
  test, nhưng **chỉ chạy qua CLI thủ công**, không có gì gọi nó tự động.
- Rate limiter thư viện (Phase 7) — đúng phạm vi đã ruling (không có gateway).
- `langgraph.json` + `Dockerfile` build thật thành công (Phase 8, §17.1).
- Load test + alerting logic (Phase 8) — thuần, có test, honest verdict.

## 2. Đã viết nhưng **CHƯA được ráp vào entrypoint chính** (bug nối dây)

File `src/agent/context/summarization.py`, `src/agent/context/limit_output.py`,
`src/agent/context/subagents.py` tồn tại, có test riêng (`tests/test_context.py`)
**pass với `create_deep_agent(...)` gọi trực tiếp trong test** — nhưng
`src/agent/graph.py::build_agent()`, vốn là **điểm xây dựng duy nhất** mà mọi
task khác (server, load_test, dreaming...) đều dùng, **không import và không
truyền 3 thứ này vào `create_deep_agent`**.

Hệ quả thực tế khi chạy production qua `src/agent/server.py:graph`:

- KHÔNG có ngưỡng summarization tùy chỉnh → dùng mặc định fraction 0.85 của
  deepagents (quá cao cho model rẻ, có thể tràn context trước khi tóm tắt).
- KHÔNG có `LimitToolOutputMiddleware` → 1 tool trả về payload khổng lồ (DB
  dump, crawl output...) có thể làm nổ token budget ngay lập tức.
- KHÔNG có research subagent (`RESEARCH_SUBAGENT`) → agent chính tự làm hết
  việc lookup dài thay vì cô lập context qua subagent.

➜ Xem `03-plan-context-memory-middleware.md`.

## 3. Chưa có: "computer-use" tool thật sự

Checklist yêu cầu agent "thao tác máy tính như con người" (file/folder, bash,
web search...). Hiện trạng:

- `execute` chỉ chạy được qua 2 backend: `RestrictedShellSandbox` (đọc-only,
  allowlist rất hẹp: `pwd/echo/ls/cat/head/tail/wc/grep/sort`) hoặc
  `LocalShellBackend` (dev-only, KHÔNG cô lập, có cảnh báo bảo mật rõ ràng
  trong chính docstring — không được dùng production).
- **Không có sandbox ghi-được, cô lập, an toàn cho production** — `BaseSandbox`
  (ABC) tồn tại trong deepagents nhưng chưa có implementation Docker/VM nào
  trong repo kế thừa nó cho write-mode.
- **Không có web search tool** nào được wire — plan gốc (`deepagents-langgraph-
  backend-plan.md` §4.2) có nhắc `TavilySearch`/`WebSearch` như ví dụ nhưng
  chưa từng implement.
- **Không có browser/computer-use tool** (click, screenshot, form-fill...).
- MCP: có 1 fixture server (`get_weather`, `echo`) chỉ phục vụ test hạ tầng
  MCP, không phải tool sản xuất thật.

➜ Xem `01-plan-tooling-computeruse.md`.

## 4. Chưa có: Config tập trung + deploy stack đầy đủ

- Không có `Settings`/`Config` class tập trung (pydantic-settings hay tương
  đương). Model, DB URL, sandbox timeout, rate-limit capacity, dreaming
  thresholds... nằm rải rác dưới dạng hằng số module-level ở >10 file khác
  nhau (`DEFAULT_MAX_AGE_SECONDS`, `DEFAULT_MAX_LENGTH`,
  `_DEFAULT_TIMEOUT_SECONDS`, `stale_after_days=30` mặc định CLI, v.v.).
- Không có `.env.example` liệt kê toàn bộ biến môi trường thực sự cần
  (`DATABASE_URL`, `AGENT_MODEL`, `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`,
  `LANGSMITH_*`, `TAVILY_API_KEY` nếu thêm web search...).
- `docker-compose.yml` chỉ có Postgres — không có service cho chính agent
  server (`langgraph up` chạy rời, không compose cùng DB).
- Không có CI (build image, chạy test, `langgraph validate`) — mọi thứ ở
  Phase 8 đều là lệnh chạy tay, không tự động hoá.

➜ Xem `02-plan-config-deployment.md`.

## 5. Chưa có: middleware mở rộng được (scalable) + tự động hoá Dreaming

- `build_agent()` không có tham số `middleware: list = ()` để người gọi thêm
  middleware của riêng họ mà không sửa source — mọi middleware mới phải được
  hardcode vào `graph.py`.
- `enqueue` (trigger Dreaming) có trong `build_agent` nhưng **`server.py`
  không truyền nó** → trong production thật, Dreaming **không bao giờ được
  enqueue** trừ khi ai đó tự sửa `server.py`. Cold-scan/consolidate/alerts chỉ
  chạy khi operator gõ lệnh tay — không có cron/scheduler nào trong repo.

➜ Xem `03-plan-context-memory-middleware.md` (mục scheduler).

## 6. Ưu tiên đề xuất (nếu chỉ làm được 1 phần)

1. **Cao nhất, rẻ nhất, rủi ro cao nhất nếu bỏ qua**: ráp lại
   `build_agent()` với summarization + limit-output + middleware list mở
   (Phase A trong file 03) — đây là bug, không phải feature thiếu.
2. **Cao**: 1 sandbox production ghi-được thật sự cô lập (Docker-based
   `BaseSandbox`) — nếu không có, "operator" role hiện tại chỉ an toàn trên
   giấy vì `LocalShellBackend` là thứ duy nhất unlock được `execute` ghi-được.
3. **Trung bình**: web search tool + config tập trung + `.env.example`.
4. **Trung bình-thấp**: scheduler cho Dreaming, docker-compose full stack, CI.
