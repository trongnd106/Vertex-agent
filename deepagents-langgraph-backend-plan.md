# Plan xây dựng Backend Agent bằng DeepAgents (trên nền LangGraph/LangChain)
### (Skill mở rộng · Built-in Tool đầy đủ · Context Management · Session Memory · Long-term Memory · Self-Improvement "Dreaming")

---

## 1. Vì sao chọn DeepAgents thay vì tự dựng LangGraph từ đầu

`deepagents` là thư viện chính thức của LangChain, xây trên nền LangGraph, lấy cảm hứng từ Claude Code / Deep Research / Manus. Nó đã có sẵn: planning tool, filesystem ảo để quản lý context, cơ chế spawn subagent, và (từ cuối 2025) hỗ trợ **Agent Skills theo đúng chuẩn SKILL.md của Anthropic** thông qua `deepagents-cli` — tức là hệ skill dạng folder mà bạn muốn đã có sẵn 80%, không cần tự viết loader.

So với việc tự dựng bằng LangGraph thuần: bạn tiết kiệm được phần "graph xương sống" (planning node, subagent node, tool node), chỉ cần tập trung vào 2 phần chưa có sẵn: **long-term memory** và **Dreaming**. Model-agnostic là điểm khác biệt lớn nhất so với Claude Agent SDK — LangChain hỗ trợ Anthropic, OpenAI, Gemini, DeepSeek, local model (Ollama)... nên bạn không bị khoá vào 1 nhà cung cấp.

| Tiêu chí | Ý nghĩa kỹ thuật | Cơ chế tương ứng |
|---|---|---|
| Skill dễ mở rộng | Thêm folder `skills/<name>/SKILL.md` là agent tự nhận diện | `deepagents` skill loader (chuẩn SKILL.md, progressive disclosure) |
| Built-in tool đầy đủ | Không tự viết executor cơ bản | Tool có sẵn của `deepagents` (file ops, planning) + tool chuẩn LangChain (`WebSearch`, `Python REPL`, `Shell`...) |
| Quản lý context tốt | Không tràn context, biết tóm tắt/offload | Virtual filesystem, subagent isolation, `trim_messages`, summarization node |
| Memory trong session | Nhớ hội thoại + tool call trong 1 phiên | LangGraph **Checkpointer** (thread-scoped) |
| Long-term memory | Nhớ xuyên suốt nhiều session/user | LangGraph **Store** + **LangMem** (namespace theo `user_id`) |
| Self-improvement (Dreaming) | Tự rút bài học sau mỗi phiên, cải thiện dần | **Không có sẵn** — tự xây bằng background graph + LangMem "memory manager" |

---

## 2. Kiến trúc tổng quan

```
┌───────────────────────────────────────────────────────────────┐
│                        Web App (Frontend)                       │
└───────────────────────────┬─────────────────────────────────────┘
                             │ REST/WebSocket (thread_id, user_id)
┌───────────────────────────▼─────────────────────────────────────┐
│                    API Gateway / Backend Service                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │   Deep Agent (LangGraph graph, tạo bằng deepagents)      │     │
│  │   - create_deep_agent(tools, skills_dir, model, ...)      │     │
│  │   - Planning node → Tool node → Subagent node             │     │
│  └───────┬───────────────────────────┬───────────────────────┘     │
│          │                           │                             │
│  ┌───────▼────────┐        ┌─────────▼──────────┐                 │
│  │  skills/        │        │  Tools Layer         │                 │
│  │  (SKILL.md)     │        │  - Built-in LC tools  │                 │
│  │  progressive    │        │  - Custom tools       │                 │
│  │  disclosure     │        │  - MCP servers (adapter)│                │
│  └────────────────┘        └─────────────────────┘                 │
│          │                           │                             │
│  ┌───────▼───────────────────────────▼───────────────────────┐     │
│  │      Context Manager (virtual FS + summarization +          │     │
│  │      subagent context isolation + trim_messages)             │     │
│  └───────┬───────────────────────────────────────────────────┘     │
│          │                                                         │
│  ┌───────▼────────┐   ┌──────────────────┐   ┌──────────────────┐ │
│  │ Checkpointer    │   │ Dreaming Graph    │   │ LangGraph Store   │ │
│  │ (short-term,    │──▶│ (background,      │──▶│ (long-term memory,│ │
│  │  thread-scoped) │   │  scheduled/queue) │   │  namespace/user)  │ │
│  │ Postgres/Redis  │   └──────────────────┘   │ Postgres+pgvector  │ │
│  └────────────────┘                          │  hoặc LangMem       │ │
│                                                └──────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

---

## 3. Tech stack đề xuất

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Framework agent | `deepagents` (Python; JS cũng có) trên nền LangGraph | Có sẵn planning + subagent + skill loader chuẩn SKILL.md |
| Model provider | Bất kỳ (Anthropic, OpenAI, DeepSeek, Gemini, Ollama local...) qua `init_chat_model` của LangChain | Model-agnostic, dễ đổi/so sánh chi phí |
| Short-term memory (checkpointer) | `PostgresSaver` (production) hoặc `MemorySaver` (dev/test) | Thread-scoped, tự động lưu state mỗi bước graph |
| Long-term memory | LangGraph `Store` (`PostgresStore` + pgvector) hoặc **LangMem** (thư viện chính thức của LangChain cho long-term memory) | LangMem có sẵn "memory manager" + hot-path/background extraction, giảm công tự viết |
| Job queue cho Dreaming | Celery / BullMQ / hoặc LangGraph Cron (Platform) | Xử lý bất đồng bộ, retry, lập lịch |
| MCP servers | `langchain-mcp-adapters` | Kết nối tool ngoài (CRM, DB nội bộ...) theo chuẩn MCP, dùng chung với Claude nếu cần |
| Observability | LangSmith (native cho LangGraph) hoặc OpenTelemetry | Trace từng node, token usage, cost per thread |
| Vector search (nếu tự viết long-term store) | pgvector / Qdrant / Weaviate | Semantic search cho retrieval memory |

---

## 4. Chi tiết từng cấu phần

### 4.1. Hệ thống Skill (folder `skills/`)

**Cấu trúc giống hệt chuẩn Anthropic SKILL.md** (deepagents đã hỗ trợ native từ bản CLI mới nhất):

```
skills/
├── customer-support/
│   └── SKILL.md
├── data-analysis/
│   ├── SKILL.md
│   └── scripts/
│       └── analyze.py
├── code-review/
│   └── SKILL.md
└── invoice-processing/
    └── SKILL.md
```

**Nguyên tắc:**
- Front-matter `name` + `description` rõ ràng — đây là phần duy nhất được load mặc định (progressive disclosure), giúp agent quyết định có cần đọc toàn bộ SKILL.md hay không mà không tốn context.
- Nội dung SKILL.md viết theo dạng hướng dẫn quy trình, không phải tài liệu tham khảo chung chung.
- Vì deepagents chạy trên virtual filesystem, script hỗ trợ trong skill có thể được agent đọc/thực thi qua tool file-system + code-exec sẵn có, không cần viết loader riêng.

**Nạp skill vào agent:**
```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    tools=custom_tools,
    skills_dir="./skills",   # tự động quét + progressive disclosure
    model="claude-sonnet-4-6",  # hoặc bất kỳ model nào qua init_chat_model
)
```

**Quy trình review skill mới:** giữ nguyên nguyên tắc như plan cũ — CI chạy test case mẫu, review `description` để tránh chồng chéo phạm vi kích hoạt giữa các skill, gắn version/tag để rollback.

---

### 4.2. Built-in Tool + Custom Tool

**3 lớp tool:**

1. **Tool có sẵn của deepagents**: file ops trên virtual filesystem (`ls`, `read_file`, `write_file`, `edit_file`), planning/todo tool, subagent-spawn tool — không cần code thêm.
2. **Tool chuẩn LangChain**: `TavilySearch`/`WebSearch`, `PythonREPLTool`, `ShellTool`, `RequestsTool`... khai báo trực tiếp trong danh sách `tools` khi tạo agent.
3. **Custom tool + MCP server**: viết bằng `@tool` decorator cho logic nghiệp vụ riêng (VD `query_order_db`, `create_ticket`); kết nối hệ thống ngoài (CRM, DB nội bộ, payment API) qua `langchain-mcp-adapters` — dùng chung định nghĩa MCP với các agent khác (kể cả agent Claude) nếu công ty có nhiều agent framework song song.

**Nguyên tắc bảo mật:**
- Danh sách tool cấp cho từng loại agent/role là ranh giới cứng — audit định kỳ.
- Với `ShellTool`/code-exec: luôn chạy trong sandbox (container riêng, không share filesystem thật với host) — deepagents dùng virtual filesystem mặc định nên rủi ro thấp hơn Bash thật, nhưng nếu bật tool truy cập filesystem thật (VD đọc file khách hàng) vẫn phải giới hạn path.

---

### 4.3. Quản lý Context

| Kỹ thuật | Áp dụng |
|---|---|
| **Virtual filesystem của deepagents** | Kết quả trung gian (research dài, log tool) ghi ra "file" ảo thay vì nhét thẳng vào context — agent chỉ đọc lại khi cần, giống cách Claude Code quản lý context |
| **Subagent context isolation** | Việc phụ (tìm kiếm sâu, đọc tài liệu dài, phân tích dữ liệu) giao cho subagent riêng — subagent trả kết quả tóm tắt, không làm phình context agent chính (đây là lý do chính deepagents được sinh ra) |
| **Summarization node** | Thêm 1 node trong graph tự tóm tắt lịch sử hội thoại khi vượt ngưỡng token, trước khi gọi model chính (tương đương `PreCompact` hook bên Claude Agent SDK) |
| **`trim_messages` / message windowing** | Cắt bớt message cũ theo token budget trước mỗi lần gọi model, giữ system prompt + N message gần nhất |
| **Giới hạn số bước (`recursion_limit`)** | Ngăn graph loop vô hạn, tương đương `max_turns` |
| **Tool result truncation** | Tool trả dữ liệu lớn (query DB, crawl web) phải tóm tắt/giới hạn trước khi đưa vào state |

---

### 4.4. Memory trong 1 session (Checkpointer — short-term)

- LangGraph tự động lưu **toàn bộ state** (messages, tool calls, kết quả trung gian, virtual filesystem) sau mỗi bước graph, gắn với `thread_id`, thông qua **Checkpointer**.
- Việc cần làm: chọn checkpointer phù hợp production.
  ```python
  from langgraph.checkpoint.postgres import PostgresSaver

  with PostgresSaver.from_conn_string(DB_URL) as checkpointer:
      checkpointer.setup()
      agent = create_deep_agent(tools=..., skills_dir="./skills")
      graph = agent.compile(checkpointer=checkpointer)
  ```
- Resume session: chỉ cần gọi lại `graph.invoke(..., config={"configurable": {"thread_id": id}})` — LangGraph tự load lại state, không cần tự viết logic resume.
- TTL: tự implement job dọn thread cũ (checkpointer không tự có TTL sẵn như Redis) — có thể dùng Redis-backed checkpointer (`langgraph-checkpoint-redis`) nếu cần TTL tự động.

---

### 4.5. Long-term Memory (xuyên suốt nhiều session)

Đây là phần LangGraph **có hỗ trợ sẵn ở mức hạ tầng** (khác với Claude Agent SDK) — thông qua **Store**, và bạn có thể dùng thêm **LangMem** để giảm công tự viết pipeline trích xuất.

**Thiết kế:**

1. **Store API** (built-in LangGraph): key-value + semantic search theo namespace, thường tổ chức `(user_id, "memories")`.
   ```python
   from langgraph.store.postgres import PostgresStore

   store = PostgresStore.from_conn_string(DB_URL, index={"embed": embeddings_model, "dims": 1536})
   graph = agent.compile(checkpointer=checkpointer, store=store)
   ```
2. **Ghi memory:**
   - **Hot-path**: agent có 1 tool `save_memory(content, category)` — tự chủ động gọi khi phát hiện thông tin quan trọng ngay trong lúc chat (giống cách Letta để agent tự quyết định lúc nào cần "nhớ").
   - **Background** (qua Dreaming — xem mục 4.6): review lại cả phiên sau khi kết thúc, rút trích toàn diện hơn.
3. **Đọc memory (retrieval):**
   - Trước khi agent xử lý prompt đầu tiên của session mới → query `store.search(namespace, query=user_input, limit=k)` (semantic search top-k, k thường 5–10) → inject vào system prompt hoặc để agent tự gọi tool `recall_memory`.
4. **LangMem** (tuỳ chọn, khuyên dùng để đỡ tự viết): cung cấp sẵn `create_memory_store_manager` — 1 "memory manager" chạy nền, tự động trích xuất fact/preference từ hội thoại theo schema bạn định nghĩa, ghi vào Store, xử lý cả việc merge/update memory trùng lặp.

---

### 4.6. Self-Improvement — "Dreaming" (background self-review)

Không có sẵn trong deepagents/LangGraph dưới dạng 1 flag, nhưng dễ dựng hơn bên Claude Agent SDK vì Store + LangMem đã có sẵn phần "nơi lưu", bạn chỉ cần tự viết **graph review** + **trigger**.

**Thiết kế:**

1. **Trigger:**
   - Node cuối trong graph chính (khi agent trả lời xong 1 turn hoặc kết thúc session) → enqueue job Dreaming thay vì xử lý đồng bộ (dùng `after_agent` hook nếu dùng LangGraph Platform, hoặc tự thêm bước cuối trong graph định nghĩa bằng LangGraph thuần).
   - Cron job quét các `thread_id` đã "nguội" (không hoạt động > N phút) chưa được review.

2. **Dreaming Graph (chạy nền, model rẻ hơn — VD Haiku, DeepSeek-V4-Flash, hoặc GPT-4o-mini):**
   ```
   Input: toàn bộ checkpoint history của thread (messages, tool calls, tool results)
   Xử lý:
     a. Gọi 1 lần model rẻ với prompt:
        "Đọc lại phiên làm việc này. Rút ra:
         - Thông tin/preference của user nên nhớ lâu dài
         - Bài học/lỗi cần tránh lần sau (VD: tool nào hay fail, cách agent xử lý sai)
         - Có mâu thuẫn gì với memory cũ trong Store không?"
     b. Structured output (Pydantic schema): {facts: [], lessons: [], conflicts: []}
     c. Nếu có conflict → không tự động ghi đè, gắn cờ "pending_review" hoặc áp rule ưu tiên memory mới hơn theo confidence.
   Output: ghi vào Store qua LangMem memory manager (hoặc trực tiếp store.put())
   ```
   - Nếu dùng LangMem: có thể tận dụng thẳng `ReflectionExecutor` của LangMem — chạy sau khi conversation kết thúc, tự động rút bài học và cập nhật vào Store mà không cần tự viết toàn bộ pipeline extraction.

3. **Consolidate định kỳ:** job tuần gộp memory trùng, hạ `confidence`/xoá memory lỗi thời không được truy xuất lâu.

4. **Vòng lặp self-improvement thực sự** (khác biệt so với plan Claude Agent SDK — đáng làm thêm ở đây vì LangGraph dễ A/B test hơn):
   - Dreaming Graph không chỉ rút "facts" mà còn rút **lesson về hiệu năng agent** (VD: "tool X thường trả lỗi khi input Y", "skill Z bị kích hoạt sai ngữ cảnh").
   - Ghi các lesson này vào 1 namespace riêng `("system", "lessons")` trong Store.
   - Định kỳ, 1 job tổng hợp các lesson → đề xuất sửa `description` của skill/tool hoặc sửa system prompt → tạo PR tự động (hoặc để người review) — đây là bước biến "Dreaming" từ chỉ nhớ user thành thực sự **tự cải thiện hành vi agent**.

**Checklist thiết kế Dreaming:**
- [ ] Chọn model rẻ cho review (tách khỏi model chính dùng khi user đang chờ)
- [ ] Định nghĩa schema structured output cho rút trích (Pydantic)
- [ ] Cơ chế xử lý conflict giữa memory mới/cũ
- [ ] Giới hạn top-k khi retrieval (tránh tràn context)
- [ ] Cơ chế consolidate/xoá memory lỗi thời
- [ ] Namespace riêng cho "lesson về agent" (khác với "fact về user") để phục vụ self-improvement thực sự
- [ ] Logging: mỗi memory record trace được về `thread_id` gốc

---

## 5. Cấu trúc thư mục dự án đề xuất

```
project-root/
├── skills/                        # SKILL.md theo chuẩn Anthropic, deepagents tự load
├── src/
│   ├── agent/
│   │   ├── graph.py               # create_deep_agent(...) + compile với checkpointer/store
│   │   ├── tools/                 # Custom tool (@tool decorator)
│   │   ├── mcp/                   # Cấu hình MCP servers (langchain-mcp-adapters)
│   │   └── context/               # Summarization node, trim_messages config
│   ├── memory/
│   │   ├── checkpointer.py        # PostgresSaver / Redis checkpointer setup
│   │   ├── store.py                # PostgresStore + embeddings config
│   │   ├── langmem_manager.py     # LangMem memory manager / ReflectionExecutor
│   │   └── dreaming_graph.py      # Background review graph
│   ├── api/                        # REST/WebSocket endpoints
│   └── config/
├── tests/
│   ├── skills/
│   └── memory/
└── infra/                          # Docker/K8s, Postgres+pgvector, Redis, job queue
```

---

## 6. Roadmap triển khai theo Phase — mô tả chi tiết từng bước

> **Lưu ý về độ chính xác:** phần dưới đây được viết sau khi thực sự `pip install deepagents langgraph langchain langmem` và đọc trực tiếp source code (`graph.py`, `middleware/skills.py`, `middleware/memory.py`, `backends/store.py`...) ở version `deepagents==0.7.9`, `langgraph==1.2.11`, `langchain==1.3.18`, `langmem==0.0.30`. API có thể đổi ở version khác — **luôn tự khám phá lại bằng các lệnh ở Phase 0** trước khi code, đừng tin mù quáng vào ví dụ code cũ (kể cả của chính plan này).

---

### Phase 0 — Nền tảng & khám phá thư viện

**Mục tiêu:** không code gì vội — trước tiên tự "đọc" thư viện để biết chính xác API đang có, vì tài liệu online thường trễ hơn code thực tế.

1. **Cài đặt và xác định version:**
   ```bash
   pip install deepagents langgraph langchain langmem
   pip show deepagents langgraph langchain langmem | grep -E "Name|Version|Location"
   ```
   → Ghi lại version vào `requirements.txt`/`pyproject.toml`, pin cứng version để tránh breaking change (deepagents còn <1.0.0, API đổi khá nhanh).

2. **Khám phá public API bằng cách đọc `__init__.py`** (đây là danh sách đầy đủ những gì bạn được phép import):
   ```bash
   python3 -c "import deepagents, inspect; print(inspect.getsourcefile(deepagents))"
   cat $(python3 -c "import deepagents, os; print(os.path.dirname(deepagents.__file__))")/__init__.py
   ```
   → Từ đây thấy được các thành phần chính: `create_deep_agent`, `DeepAgentState`, `FilesystemMiddleware`, `MemoryMiddleware`, `SubAgentMiddleware`, `AsyncSubAgentMiddleware`, `RubricMiddleware`, `HarnessProfile`...

3. **Xem cấu trúc thư mục package** để biết những "khối" nào có sẵn (middleware, backend):
   ```bash
   find $(python3 -c "import deepagents, os; print(os.path.dirname(deepagents.__file__))") -name "*.py" | grep -v pycache
   ```
   → Sẽ thấy `middleware/skills.py`, `middleware/memory.py`, `middleware/subagents.py`, `middleware/summarization.py`, `middleware/filesystem.py`, và `backends/{state,filesystem,store,sandbox,composite}.py` — đây chính là bản đồ để biết "context management", "skill", "long-term memory (qua Store backend)" nằm ở đâu, khỏi phải đoán.

4. **Đọc signature + docstring của hàm quan trọng nhất trước khi dùng:**
   ```bash
   python3 -c "from deepagents import create_deep_agent; import inspect; print(inspect.signature(create_deep_agent))"
   python3 -c "from deepagents import create_deep_agent; help(create_deep_agent)" | less
   ```
   → Đây là bước quan trọng nhất, vì docstring của `create_deep_agent` liệt kê **chính xác thứ tự middleware được ráp** (Skills → Filesystem → SubAgent → Summarization → PatchToolCalls → AsyncSubAgent → [middleware của bạn] → PromptCaching → Memory → HumanInTheLoop), giúp bạn biết chèn middleware tuỳ chỉnh ở đâu.

5. **Khám phá CLI của LangGraph** (dùng để chạy dev server, build Docker image sau này):
   ```bash
   pip install langgraph-cli
   langgraph --help
   langgraph new --help      # tạo project từ template
   langgraph dev --help      # chạy dev server + LangGraph Studio local
   ```

6. **Dựng hạ tầng local (docker-compose):** Postgres (dùng chung cho checkpointer + store, bật extension `pgvector` nếu định tự làm semantic search), Redis (nếu chọn checkpointer/queue bằng Redis).

7. **Chạy "hello world" để xác nhận toàn bộ chuỗi cài đặt hoạt động:**
   ```python
   from deepagents import create_deep_agent

   agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")  # hoặc "openai:gpt-5.5"
   result = agent.invoke({"messages": [{"role": "user", "content": "Xin chào, bạn có tool gì?"}]})
   print(result["messages"][-1].content)
   ```
   - [ ] Repo khởi tạo, `requirements.txt` pin version
   - [ ] Đã đọc xong `create_deep_agent` docstring + biết thứ tự middleware
   - [ ] Docker-compose Postgres/Redis chạy được
   - [ ] "Hello world" agent trả lời thành công

---

### Phase 1 — Hệ thống Skill

**Khám phá trước:** đọc `middleware/skills.py` (module docstring giải thích rất kỹ kiến trúc "sources"):
```bash
python3 -c "from deepagents.middleware.skills import SkillsMiddleware; help(SkillsMiddleware)" | less
```
Điểm quan trọng cần nắm: skill không nạp qua tham số `skills_dir` (đây là điểm plan bản trước ghi **chưa chính xác** so với API thực tế) mà qua `skills=[...]`, một **list các source path**, mỗi path trỏ tới 1 thư mục chứa các skill-folder (mỗi folder có `SKILL.md`). Nhiều source được nạp theo thứ tự, source sau đè source trước nếu trùng tên skill (dùng để layer: skill base → skill của team → skill riêng project).

**Các bước:**
1. Tạo cấu trúc thư mục skill đúng chuẩn:
   ```
   skills/
   ├── customer-support/SKILL.md
   ├── data-analysis/SKILL.md
   └── code-review/SKILL.md
   ```
   Mỗi `SKILL.md` bắt buộc có YAML front-matter `name` (≤64 ký tự, chữ thường + số + gạch ngang) và `description` (≤1024 ký tự) — 2 trường này được nạp mặc định (progressive disclosure), toàn bộ nội dung còn lại chỉ được agent đọc khi thực sự cần dùng skill.

2. Chọn backend phù hợp để skill nạp từ đâu:
   - Dev/test nhanh, không cần filesystem thật: `StateBackend()` — nạp skill qua `agent.invoke(..., files={"/skills/user/customer-support/SKILL.md": "..."})`.
   - Production, skill nằm trên đĩa thật: `FilesystemBackend(root_dir="./skills")`.
   ```python
   from deepagents import create_deep_agent
   from deepagents.backends.filesystem import FilesystemBackend

   agent = create_deep_agent(
       model="anthropic:claude-sonnet-4-6",
       backend=FilesystemBackend(root_dir="."),
       skills=["/skills/"],   # path POSIX, tương đối với root_dir của backend
   )
   ```

3. Viết quy chuẩn nội bộ SKILL.md (template + checklist), CI test activation: given prompt X → skill Y phải được kích hoạt (kiểm tra qua log tool-call `list_skills`/`read_skill` mà `SkillsMiddleware` expose).

- [ ] Đã đọc `middleware/skills.py` để hiểu cơ chế "sources" + progressive disclosure
- [ ] 2-3 skill mẫu hoạt động đúng qua `FilesystemBackend`
- [ ] Test tự động activation

---

### Phase 2 — Tool system

**Khám phá trước:** đọc docstring `create_deep_agent` phần tool built-in mặc định:
```bash
python3 -c "from deepagents import create_deep_agent; help(create_deep_agent)" | grep -A 8 "By default"
```
Kết quả thực tế: mặc định agent đã có sẵn `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep` (thao tác file), `execute` (chạy shell command — **chỉ hoạt động nếu backend implement `SandboxBackendProtocol`**, còn lại trả lỗi), và `task` (gọi subagent). Việc truyền `tools=[...]` vào `create_deep_agent` là **cộng thêm**, không thay thế built-in.

**Các bước:**
1. Liệt kê backend nào hỗ trợ `execute` (sandbox thật sự):
   ```bash
   python3 -c "from deepagents.backends.protocol import SandboxBackendProtocol; help(SandboxBackendProtocol)"
   ```
   → Nếu cần code-exec an toàn, dùng `deepagents.backends.sandbox` (đã có sẵn trong package) thay vì tự viết executor.

2. Viết custom tool bằng `@tool` decorator chuẩn LangChain cho nghiệp vụ riêng:
   ```python
   from langchain_core.tools import tool

   @tool
   def query_order_db(order_id: str) -> str:
       """Tra cứu thông tin đơn hàng theo mã đơn."""
       ...
   ```

3. Kết nối MCP server (nếu cần hệ thống ngoài):
   ```bash
   pip install langchain-mcp-adapters
   python3 -c "from langchain_mcp_adapters.client import MultiServerMCPClient; help(MultiServerMCPClient)"
   ```

4. Giới hạn tool theo role: dùng `HarnessProfile(excluded_tools=[...])` (xem trong `deepagents.profiles.harness`) để bớt built-in tool cho agent end-user, thay vì mở hết.

- [ ] Đã xác nhận backend nào bật được `execute` an toàn (sandbox)
- [ ] 2-3 custom tool nghiệp vụ chạy được, có unit test
- [ ] Thử kết nối 1 MCP server thật
- [ ] Đã cấu hình `HarnessProfile` giới hạn tool theo role

---

### Phase 3 — Quản lý Context

**Khám phá trước:**
```bash
python3 -c "from deepagents.middleware.summarization import *" 2>&1 | head
python3 -c "from deepagents.middleware.filesystem import FilesystemMiddleware; help(FilesystemMiddleware)" | less
```
Thực tế: `SummarizationMiddleware` (đến từ `langchain.agents.middleware`, deepagents chỉ ráp sẵn vào chuỗi) đã **được thêm mặc định** vào stack của `create_deep_agent` — nghĩa là context management cơ bản không cần bạn tự viết node, chỉ cần cấu hình ngưỡng.

**Các bước:**
1. Tìm tham số cấu hình ngưỡng summarization/token budget:
   ```bash
   python3 -c "from langchain.agents.middleware import SummarizationMiddleware; import inspect; print(inspect.signature(SummarizationMiddleware.__init__))"
   ```
   → Truyền middleware đã cấu hình lại (model tóm tắt, ngưỡng token) qua tham số `middleware=[...]` của `create_deep_agent` để override middleware mặc định nếu cần custom.

2. Cấu hình subagent cho việc phụ (giữ context chính gọn):
   ```python
   from deepagents import create_deep_agent, SubAgent

   research_subagent: SubAgent = {
       "name": "researcher",
       "description": "Tìm kiếm và đọc tài liệu dài, trả về bản tóm tắt.",
       "system_prompt": "Bạn là chuyên gia research...",
       "tools": [web_search_tool],
   }
   agent = create_deep_agent(model=..., subagents=[research_subagent])
   ```
   → Agent chính gọi subagent qua tool `task` có sẵn; subagent chạy trong context riêng, chỉ trả kết quả tóm tắt về agent chính.

3. Middleware giới hạn kết quả tool lớn: viết middleware tuỳ chỉnh (kế thừa `AgentMiddleware`) can thiệp `on_tool_end` để cắt/tóm tắt output trước khi ghi vào state.

- [ ] Đã đọc config của `SummarizationMiddleware`, chỉnh ngưỡng phù hợp
- [ ] Ít nhất 1 subagent nghiên cứu/đọc tài liệu dài hoạt động, cô lập context tốt
- [ ] Middleware giới hạn tool-result lớn

---

### Phase 4 — Session Memory (short-term, qua Checkpointer)

**Khám phá trước:** kiểm tra package checkpointer nào thực sự tồn tại trên PyPI (đừng đoán tên package):
```bash
pip index versions langgraph-checkpoint-postgres 2>&1 || pip install langgraph-checkpoint-postgres --dry-run
python3 -c "from langgraph.checkpoint.memory import MemorySaver; help(MemorySaver)"
```

**Các bước:**
1. Dev/test: dùng `MemorySaver` (in-memory, mất khi restart) để chạy nhanh.
2. Production: cài `langgraph-checkpoint-postgres`, dùng `PostgresSaver`:
   ```python
   from langgraph.checkpoint.postgres import PostgresSaver

   with PostgresSaver.from_conn_string(DB_URL) as checkpointer:
       checkpointer.setup()  # tạo schema — chỉ chạy 1 lần / khi migrate
       graph = create_deep_agent(model=..., checkpointer=checkpointer)
       graph.invoke(
           {"messages": [...]},
           config={"configurable": {"thread_id": "user-123-session-1"}},
       )
   ```
3. Test resume: gọi lại `graph.invoke(...)` với cùng `thread_id` sau khi restart process — xác nhận state (messages, virtual filesystem) được khôi phục đầy đủ.
4. Chính sách dọn dữ liệu cũ: `checkpointer` không có TTL sẵn (khác Redis) — viết job SQL xoá `thread_id` không hoạt động > N ngày, hoặc chuyển sang checkpointer backed Redis nếu cần TTL tự động.

- [ ] `PostgresSaver` chạy được, `setup()` đã tạo schema
- [ ] Test resume session qua restart thành công
- [ ] Job dọn thread cũ

---

### Phase 5 — Long-term Memory (xuyên session)

**Khám phá trước — đây là phần cần chỉnh lại so với bản plan trước:** tham số `memory=[...]` của `create_deep_agent` **không phải** cơ chế long-term memory động — đọc thẳng source xác nhận nó chỉ nạp file `AGENTS.md` tĩnh vào system prompt (giống context/hướng dẫn dự án, luôn được load, không phải "trí nhớ" agent tự ghi):
```bash
python3 -c "from deepagents import MemoryMiddleware; help(MemoryMiddleware)" | head -40
```
Long-term memory thật sự (agent tự ghi, tự truy hồi, xuyên nhiều thread/user) phải dùng **`store` của LangGraph** — deepagents có sẵn `StoreBackend` (đọc `backends/store.py`) là adapter biến `BaseStore` thành 1 "filesystem ảo cross-thread": agent `write_file`/`read_file` vào đường dẫn trong Store, dữ liệu tồn tại xuyên suốt mọi session/thread thay vì mất khi thread kết thúc.

**Các bước:**
1. Khám phá `StoreBackend`:
   ```bash
   python3 -c "from deepagents.backends.store import StoreBackend; help(StoreBackend)" | less
   ```
2. Setup Postgres Store (song song với checkpointer, có thể dùng chung 1 DB):
   ```bash
   pip install langgraph-checkpoint-postgres   # thường bundle luôn PostgresStore
   python3 -c "from langgraph.store.postgres import PostgresStore; help(PostgresStore)"
   ```
   ```python
   from langgraph.store.postgres import PostgresStore
   from deepagents.backends.store import StoreBackend
   from deepagents.backends.composite import CompositeBackend  # ghép nhiều backend (skills trên disk + memory trên Store)

   with PostgresStore.from_conn_string(DB_URL, index={"embed": embeddings_model, "dims": 1536}) as store:
       store.setup()
       backend = CompositeBackend({
           "/skills/": FilesystemBackend(root_dir="./skills"),
           "/memory/": StoreBackend(namespace=lambda runtime: ("memories", runtime.context.user_id)),
       })
       graph = create_deep_agent(model=..., backend=backend, skills=["/skills/"], store=store, checkpointer=checkpointer)
   ```
   → Kiểm tra chính xác chữ ký `CompositeBackend`/`StoreBackend` bằng `inspect.signature` trước khi copy, vì đây là API nội bộ dễ đổi giữa các minor version.
3. Cho agent 1 hướng dẫn trong system prompt để chủ động ghi memory quan trọng vào `/memory/notes.md` (qua tool `write_file` có sẵn) — không cần viết tool `save_memory` riêng vì filesystem-as-memory đã đủ dùng.
4. Nếu muốn semantic search (không chỉ đọc file theo path) thay vì file thuần: cân nhắc dùng **LangMem** thay vì tự dựng:
   ```bash
   python3 -c "import langmem; print(langmem.__file__)"
   python3 -c "from langmem import create_memory_store_manager; help(create_memory_store_manager)"
   ```
   LangMem cung cấp sẵn "memory manager" trích xuất fact có schema (Pydantic) và ghi/merge vào cùng `BaseStore` — dùng chung hạ tầng Postgres Store ở trên, không cần đổi DB.
5. Retrieval khi bắt đầu session mới: agent tự `read_file("/memory/notes.md")` hoặc gọi `store.search(namespace, query=...)` nếu dùng LangMem semantic search, giới hạn top-k 5-10.
6. Test end-to-end: session A (thread A) ghi 1 fact → session B (thread B, cùng `user_id` trong namespace) đọc lại được.

- [ ] Đã đọc `backends/store.py` + `backends/composite.py` để hiểu cách ghép filesystem thật (skill) với Store (memory)
- [ ] Postgres Store chạy, `store.setup()` xong
- [ ] Agent tự ghi/đọc memory qua file trong `/memory/`
- [ ] (Tuỳ chọn) LangMem semantic search hoạt động
- [ ] Test cross-thread retrieval thành công

---

### Phase 6 — Dreaming / Self-improvement

**Khám phá trước:** LangMem có sẵn cơ chế review nền — kiểm tra trước khi tự viết từ đầu:
```bash
python3 -c "from langmem import ReflectionExecutor" 2>&1
python3 -c "import langmem; print([x for x in dir(langmem) if not x.startswith('_')])"
```
Nếu tồn tại `ReflectionExecutor`/tương đương trong version bạn cài, ưu tiên dùng thay vì tự viết toàn bộ pipeline; nếu không có (API có thể đã đổi tên ở version mới), tự viết 1 graph riêng theo thiết kế dưới.

**Các bước:**
1. Viết 1 graph LangGraph **riêng biệt**, độc lập với agent chính, nhận `thread_id` làm input, đọc lại lịch sử qua checkpointer:
   ```python
   history = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
   ```
2. Prompt model rẻ (Haiku/DeepSeek-V4-Flash/gpt-4o-mini) với `response_format` structured (Pydantic) — dùng thẳng cơ chế `response_format` mà `create_deep_agent`/`create_agent` đã hỗ trợ sẵn thay vì tự parse JSON:
   ```python
   from pydantic import BaseModel

   class DreamOutput(BaseModel):
       facts: list[str]
       lessons: list[str]
       conflicts: list[str]
   ```
3. Ghi kết quả vào Store: `facts` → namespace `("memories", user_id)`; `lessons` (về hành vi agent, tool hay lỗi...) → namespace riêng `("system", "lessons")` để tách biệt rõ "nhớ về user" và "tự cải thiện hệ thống".
4. Trigger: enqueue job này ở cuối turn (thêm 1 middleware `after_model`/cuối graph chính chỉ để enqueue, không xử lý đồng bộ) hoặc cron quét thread nguội — dùng Celery/BullMQ tuỳ ngôn ngữ backend.
5. Consolidate định kỳ: job đọc toàn bộ namespace `memories`, gộp trùng, hạ độ ưu tiên memory cũ không được `read_file`/`search` trong N ngày.
6. (Nâng cao) Job tuần tổng hợp namespace `("system", "lessons")` → sinh gợi ý sửa `description` skill/tool → tạo PR để người review, biến Dreaming thành vòng lặp tự cải thiện thật sự chứ không chỉ nhớ user.

- [ ] Đã kiểm tra LangMem có sẵn công cụ reflection hay phải tự viết
- [ ] Dreaming graph chạy độc lập, đọc được lịch sử qua checkpointer
- [ ] Structured output qua Pydantic, không tự parse JSON tay
- [ ] Namespace tách biệt `memories` (về user) và `lessons` (về agent)
- [ ] Job consolidate + (tuỳ chọn) job đề xuất sửa skill/prompt

---

### Phase 7 — Observability & Bảo mật

1. Khám phá tích hợp LangSmith có sẵn (deepagents build trên LangGraph nên trace tự động nếu bật):
   ```bash
   export LANGSMITH_TRACING=true
   export LANGSMITH_API_KEY=...
   ```
   → Chạy lại "hello world" ở Phase 0, kiểm tra trace xuất hiện trên LangSmith mà không cần code thêm.
2. Audit `HarnessProfile`/`excluded_tools` định kỳ theo role.
3. Rate limit theo `user_id` ở tầng API Gateway.
4. Test permission boundary: dùng `permissions=[FilesystemPermission(...)]` (mode `deny`/`interrupt`) — đọc `help(FilesystemPermission)` trước khi cấu hình để biết đúng field.

- [ ] LangSmith trace hoạt động cho mọi thread
- [ ] Audit tool theo role có checklist
- [ ] Rate limit theo user
- [ ] Test permission boundary pass

---

### Phase 8 — Triển khai & vận hành

1. Dùng chính CLI đã khám phá ở Phase 0 để build/deploy thay vì tự viết Dockerfile từ đầu:
   ```bash
   langgraph dockerfile ./Dockerfile   # sinh Dockerfile chuẩn cho LangGraph API server
   langgraph build -t my-agent:latest  # build image
   langgraph up                        # chạy local như production
   ```
2. Load test concurrency nhiều `thread_id` song song (kiểm tra Postgres checkpointer/store chịu tải).
3. Alert khi Dreaming job fail hoặc backlog queue tăng bất thường.
4. Runbook: tool lỗi, memory conflict, context overflow, checkpointer mất kết nối DB.

- [ ] Image build qua `langgraph build` chạy được
- [ ] Load test đạt ngưỡng kỳ vọng
- [ ] Alert + runbook sẵn sàng

---

## 7. Rủi ro cần lưu ý

| Rủi ro | Mức độ | Giảm thiểu |
|---|---|---|
| Long-term memory sai/lỗi thời làm agent trả lời sai | Cao | Cơ chế `confidence`, review conflict trước khi ghi đè |
| Dreaming job chạy quá nhiều gây tốn chi phí | Trung bình | Dùng model rẻ, batch nhiều thread thay vì xử lý từng cái, chạy off-peak |
| Context vẫn tràn dù có subagent/summarization | Trung bình | Giới hạn nghiêm ngặt top-k memory inject + kích thước tool result + `recursion_limit` |
| Skill chồng chéo, agent chọn sai skill | Trung bình | Review kỹ `description`, viết test case activation rõ ràng |
| Đổi model provider giữa chừng làm behavior đổi (prompt không tối ưu cho model mới) | Trung bình | Test lại toàn bộ skill/tool khi đổi model, không assume prompt portable 100% |
| Code-exec/shell tool bị lạm dụng | Cao | Sandbox bắt buộc, audit log mọi lệnh, giới hạn path filesystem thật nếu có |

---

## 8. Ghi chú quan trọng

So với plan dùng Claude Agent SDK, hướng DeepAgents/LangGraph có 2 lợi thế rõ:
1. **Model-agnostic thực sự** — đổi giữa Claude, GPT, DeepSeek, model local mà không phải đổi framework.
2. **Long-term memory có hạ tầng sẵn** (Store + LangMem) — bạn không phải tự dựng vector DB pipeline từ số 0 như bên Claude Agent SDK.

Đánh đổi: hệ sinh thái built-in tool và độ "chín" của skill loader trong `deepagents` còn non hơn Claude Code (vốn đã chạy production nhiều năm), và bạn phải tự ghép nhiều mảnh (checkpointer, store, LangMem, job queue) thay vì có 1 SDK tích hợp sẵn — đổi lại là sự linh hoạt và không bị khoá nhà cung cấp model.
