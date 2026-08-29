# Plan 01 — Computer-Use Tooling: sandbox ghi-được production, web search, thao tác máy tính

## Mục tiêu

Cho agent khả năng "dùng máy tính như con người" một cách **an toàn theo
role**: đọc/ghi file thật trong môi trường cô lập, chạy lệnh shell có kiểm
soát, tìm kiếm web, và (tuỳ chọn) điều khiển trình duyệt — mà không phá vỡ
ranh giới bảo mật đã có (`HarnessProfile.excluded_tools`,
`FilesystemPermission`).

Không động vào: `RestrictedShellSandbox` (giữ nguyên làm chế độ read-only an
toàn cho `customer-support`), `LocalShellBackend` (giữ nguyên, đánh dấu rõ hơn
là "chỉ dev/CI, không bao giờ dùng trong `build_agent` production path").

---

## Task A — `DockerSandbox`: sandbox ghi-được, cô lập thật, cho role `operator`

**Vấn đề:** `BaseSandbox` (ABC) đã tồn tại trong deepagents, nhưng chưa có
implementation nào trong repo thật sự cô lập tiến trình khỏi host. Đây là lỗ
hổng bảo mật thật nếu role `operator` (vốn giữ `execute`) chạy trên
`LocalShellBackend`.

**Thiết kế** (`src/agent/tools/docker_sandbox.py`):

1. Kế thừa `deepagents.backends.sandbox.BaseSandbox`, implement bắt buộc:
   `execute`, `upload_files`, `download_files`, `id` (đối chiếu
   `docs/phase-0-discovery.md` §13.1 — đúng 4 abstract method).
2. Mỗi phiên sandbox = 1 container Docker riêng (`docker run --rm
   --network=none --memory=512m --cpus=1 --read-only --tmpfs /tmp -v
   <workdir>:/workspace`), image tối giản (`python:3.11-slim` hoặc
   `alpine` + coreutils tuỳ nhu cầu).
3. `execute(command, timeout)`: `docker exec` vào container đã khởi tạo sẵn
   cho session đó (KHÔNG parse/interpret command — pass argv y như
   `RestrictedShellSandbox` đã làm, tránh shell injection).
4. `upload_files`/`download_files`: copy qua `docker cp`, path luôn tương đối
   `/workspace`, không cho path escape (dùng lại logic `_confine` từ
   `RestrictedShellSandbox` làm helper dùng chung — tách thành
   `src/agent/tools/_path_confinement.py`).
5. Giới hạn tài nguyên bắt buộc: `--network=none` mặc định (chỉ bật network
   khi có flag rõ ràng), timeout mặc định giống `_DEFAULT_TIMEOUT_SECONDS`,
   container tự huỷ sau timeout hoặc cuối session (`__del__`/context manager).
6. Container lifecycle: 1 container / 1 `thread_id`, tái sử dụng cho các lượt
   `execute` trong cùng session (tránh cold-start docker mỗi lần), dọn dẹp khi
   session kết thúc hoặc timeout không hoạt động (giống pattern cleanup thread
   ở `src/memory/cleanup.py`).

**Wiring vào role:**

- `build_agent(..., backend=DockerSandbox(...))` chỉ dùng cho role
  `operator`; `customer-support` **tiếp tục dùng** `RestrictedShellSandbox`
  hoặc backend mặc định hiện tại — không đổi.
- Cập nhật `docs/tool-audit-checklist.md` mục `operator`: đổi ghi chú
  "`execute` phải đi qua sandbox rim" từ tham chiếu `RestrictedShellSandbox`
  sang `DockerSandbox`.

**Test cần có** (`tests/test_docker_sandbox.py`, đánh dấu `@pytest.mark.docker`,
skip nếu daemon Docker không chạy được — theo đúng pattern `skip_postgres`):

- `execute` chạy lệnh ghi file thật, file tồn tại đúng trong container/volume,
  KHÔNG xuất hiện trên host ngoài `workdir` đã mount.
- Container không có network (`curl` ra ngoài phải fail khi `--network=none`).
- Timeout thật sự kill container/process, không treo test suite.
- `download_files`/`upload_files` roundtrip đúng nội dung, path escape bị từ
  chối giống `RestrictedShellSandbox` hiện tại.
- Không leak container: sau khi agent invoke xong + cleanup, `docker ps` không
  còn container của session đó.

**Rủi ro & mitigation:**

| Rủi ro | Mitigation |
|---|---|
| Docker daemon không có trên máy CI/dev | Test tự skip (mirror `skip_postgres`), tài liệu rõ yêu cầu Docker |
| Container escape (kernel exploit) | Ngoài phạm vi — ghi rõ trong docstring là "best-effort isolation", khuyến nghị gVisor/Kata cho môi trường thực sự nhạy cảm |
| Resource exhaustion (fork bomb trong container) | `--memory`/`--cpus`/`--pids-limit` bắt buộc trong lệnh `docker run` |

---

## Task B — Web search tool

**Thiết kế** (`src/agent/tools/web_search.py`):

1. Interface tool-agnostic: 1 hàm `search_web(query: str, max_results: int =
   5) -> str` bọc bằng `@tool`, tương tự pattern `query_order`/
   `create_support_ticket` đã có.
2. Provider mặc định: Tavily (`langchain-tavily` hoặc REST API thuần qua
   `httpx`, tránh thêm dependency nặng nếu không cần SDK) — chọn Tavily vì
   đây là lựa chọn phổ biến nhất với LangChain, dễ audit output (trả về
   snippet + url, không phải HTML thô).
3. **Không hardcode provider** — factory `build_web_search_tool(provider:
   Literal["tavily", "none"] = "tavily")` để dễ thay bằng provider khác sau
   này mà không đổi chữ ký tool.
4. Rate-limit nội bộ dùng lại `src/api/rate_limit.py::RateLimiter` (đã có sẵn,
   không viết lại) — 1 bucket riêng cho web search theo `user_id`, tránh 1
   user spam search làm cạn quota provider.
5. Output truncation: bọc kết quả qua cùng cơ chế `LimitToolOutputMiddleware`
   (Task trong file 03) thay vì tự viết truncation riêng.

**Config:** `TAVILY_API_KEY` thêm vào `.env.example` (file 02). Khi thiếu key
→ tool trả lỗi rõ ràng thay vì exception ngầm; `build_agent` chỉ thêm tool này
vào danh sách khi key tồn tại (tránh model thấy tool nhưng gọi luôn fail).

**Test:**

- Fake provider (giống `ScriptedChatModel` pattern) để test không cần mạng
  thật (Ruling M1 vẫn áp dụng cho CI).
- 1 test `@pytest.mark.livesearch` (skip mặc định) gọi Tavily thật khi có key,
  để validate thủ công giống pattern `@pytest.mark.langsmith`.

---

## Task C — (Tuỳ chọn, ưu tiên thấp) Browser / computer-use tool

Chỉ triển khai nếu có nhu cầu cụ thể (điền form web, click UI) — không phải
yêu cầu bắt buộc để "agent mạnh mẽ" ở mức backend service này. Nếu cần:

1. Đánh giá `browser-use` hoặc Playwright wrapper làm 1 `@tool` riêng
   (`navigate`, `click`, `type`, `screenshot`) chạy trong **cùng
   `DockerSandbox`** (Task A) chứ không chạy trên host — tái dùng ranh giới cô
   lập đã xây, tránh nhân đôi bề mặt tấn công.
2. Gắn vào `HarnessProfile` riêng (`browser-operator`) — KHÔNG gộp vào
   `operator` mặc định, vì đây là bề mặt rủi ro khác hẳn (network access +
   rendering nội dung web không tin cậy).
3. Ghi rõ trong `docs/tool-audit-checklist.md` nếu triển khai.

**Quyết định:** hoãn Task C cho tới khi có use-case cụ thể; Task A + B đã đủ
để đạt "agent thao tác máy tính + tìm kiếm thông tin" cho phần lớn nhu cầu
backend agent.
