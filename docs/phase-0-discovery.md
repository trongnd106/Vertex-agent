# Phase 0 — Discovery Document (deepagents `0.7.9` / langgraph `1.2.11`)

> **Nguồn dữ kiện:** đọc trực tiếp source code của **đúng version đang cài** trên đĩa —
> `deepagents` tại `/home/trong/Documents/deepagents/libs/deepagents/` và
> `langgraph` tại `/home/trong/Documents/langgraph/libs/langgraph/`, đồng thời truy vấn
> runtime qua `.venv/bin/python`. **Không** theo tài liệu online (tài liệu trễ hơn code).
> Mọi task sau **MUST** đọc file này trước khi code để tránh phải verify lại API.

---

## 1. Version chính xác (pin cứng trong `pyproject.toml`)

`uv pip list --python .venv/bin/python` (bản gốc đầy đủ trong dev report):

| Package | Version |
|---|---|
| deepagents | **0.7.9** |
| langgraph | **1.2.11** |
| langchain | **1.3.18** |
| langmem | **0.0.30** |
| langgraph-checkpoint-postgres | **3.1.2** |
| langchain-core | 1.6.0 |
| langchain-openai | 1.6.0 |
| langchain-anthropic | 1.7.0 |
| langchain-mcp-adapters | 0.3.2 |
| langgraph-cli | **0.4.31** |
| pytest | 9.1.1 |

**⇨ `pyproject.toml` pin cứng `==` cho 4 core package** (Ruling M2: requires-python `>=3.11`).

---

## 2. Bản đồ public API — `deepagents/__init__.py`

Đây là **toàn bộ** những gì được import trực tiếp từ `deepagents`:

```python
from deepagents._version import __version__
from deepagents.graph import DeepAgentState, create_deep_agent
from deepagents.middleware.async_subagents import AsyncSubAgent, AsyncSubAgentMiddleware
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemPermission, FsToolName
from deepagents.middleware.memory import MemoryMiddleware
from deepagents.middleware.rubric import RubricMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware
from deepagents.profiles.harness.harness_profiles import (
    GeneralPurposeSubagentProfile, HarnessProfile, HarnessProfileConfig, register_harness_profile,
)
from deepagents.profiles.provider.provider_profiles import (
    ProviderProfile, register_provider_profile,
)
```

`__all__ = ["AsyncSubAgent", "AsyncSubAgentMiddleware", "CompiledSubAgent", "DeepAgentState",
"FilesystemMiddleware", "FilesystemPermission", "FsToolName", "GeneralPurposeSubagentProfile",
"HarnessProfile", "HarnessProfileConfig", "MemoryMiddleware", "ProviderProfile", "RubricMiddleware",
"SubAgent", "SubAgentMiddleware", "__version__", "create_deep_agent", "register_harness_profile",
"register_provider_profile"]`

**Xác nhận so với brief:** brief "Phase 0" của plan liệt kê `AsyncSubAgentMiddleware` ✓ và
`RubricMiddleware` ✓ — **cả hai đều TỒN TẠI** (trong `__all__`). `HarnessProfile` ✓ tồn tại.

### 2.1. Các module `backends/*.py`

| Module | Class public | Mục đích (1 dòng) |
|---|---|---|
| `backends/state.py` | `StateBackend` | Filesystem ảo trong **state in-memory** của graph (mặc định, không persistent, không có `execute`). |
| `backends/filesystem.py` | `FilesystemBackend` | Filesystem **thật trên đĩa** (`root_dir`), không sandbox / không `execute`. |
| `backends/store.py` | `StoreBackend`, `NamespaceFactory` | Biến `BaseStore` của LangGraph thành filesystem **cross-thread** (long-term memory); scope theo `namespace` factory. |
| `backends/composite.py` | `CompositeBackend` | Ghép nhiều backend theo **path prefix** (vd `/skills/` → disk, `/memory/` → Store). |
| `backends/sandbox.py` | `BaseSandbox` (ABC) | Base class implement `SandboxBackendProtocol` để bạn kế thừa tạo **isolated** code-exec (Docker/VM). |
| `backends/local_shell.py` | `LocalShellBackend`, `DEFAULT_EXECUTE_TIMEOUT` | `FilesystemBackend` + **unrestricted local shell `execute`** (`SandboxBackendProtocol`), **dev only**. |
| `backends/context_hub.py` | `ContextHubBackend` | Backend cho Context Hub (LangSmith platform). |
| `backends/langsmith.py` | `LangSmithSandbox` | Sandbox backend chạy qua LangSmith remote sandbox. |

`deepagents.backends.__init__` export: `DEFAULT_EXECUTE_TIMEOUT, BackendProtocol, CompositeBackend,
ContextHubBackend, FilesystemBackend, LangSmithSandbox, LocalShellBackend, NamespaceFactory,
StateBackend, StoreBackend`.

### 2.2. Các module `middleware/*.py`

| Module | Class public | Mục đích |
|---|---|---|
| `middleware/skills.py` | `SkillsMiddleware` | Load skill từ **sources** trong backend, progressive disclosure (chỉ đọc front-matter name/description). |
| `middleware/memory.py` | `MemoryMiddleware` | Nạp file `AGENTS.md` **tĩnh** vào system prompt (**KHÔNG** phải memory động). |
| `middleware/filesystem.py` | `FilesystemMiddleware`, `FilesystemPermission`, `FsToolName` | Các tool file ops (`ls/read/write/edit/glob/grep/execute`) + permission rules (`allow/deny/interrupt`). |
| `middleware/subagents.py` | `SubAgentMiddleware`, `SubAgent`, `CompiledSubAgent` | Subagent synchronous (tool `task`). |
| `middleware/async_subagents.py` | `AsyncSubAgentMiddleware`, `AsyncSubAgent` | Subagent chạy nền / remote (async-subagent tools). |
| `middleware/summarization.py` | `SummarizationMiddleware`, `SummarizationToolMiddleware`, `create_summarization_tool_middleware`, `DEEPAGENTS_DEFAULT_SUMMARY_PROMPT` | Tự tóm tắt + offload lịch sử khi vượt token budget. |
| `middleware/rubric.py` | `RubricMiddleware`, `RubricState`, `RubricResult`, `RubricEvaluation`, `CriterionEval/Pass/Fail`, `GraderResponse`, `GraderVerdict` | Đánh giá/justify output theo rubric (identity/critical/simple). |
| `middleware/patch_tool_calls.py` | `PatchToolCallsMiddleware` | Vá tool-call khi model trả sai shape (batch). |
| `middleware/permissions.py` | — | Permission cho fileops ở tầng contract. |

*(Ngoài ra còn các module nội bộ `_*.py`: `_fs_interrupt`, `_message_eviction`, `_overflow_clip`,
`_prompt_caching`, `_state`, `_tool_exclusion`, `_utils`, `_video`.)*

### 2.3. `profiles/*.py` (harness)

- `profiles/harness/harness_profiles.py`: `HarnessProfile`, `HarnessProfileConfig`,
  `GeneralPurposeSubagentProfile`, `register_harness_profile`.
- `profiles/provider/provider_profiles.py`: `ProviderProfile`, `register_provider_profile`.
- **KHÔNG có `skills_dir` và KHÔNG có `harness_profile` parameter trong `create_deep_agent`** —
  đây là điểm plan brief ghi **chưa chính xác** (xem mục 8).

---

## 3. `create_deep_agent` — signature & docstring (verbatim-critical)

**Signature thực tế** (đã verify runtime):

```
create_deep_agent(
    model=None,
    tools=None,
    *,
    system_prompt=None,
    middleware=(),
    subagents=None,
    skills=None,
    memory=None,
    permissions=None,
    backend=None,
    interrupt_on=None,
    response_format=None,
    state_schema=None,
    context_schema=None,
    checkpointer=None,
    store=None,
    debug=False,
    name=None,
    cache=None,
)
```

Trả về: `CompiledStateGraph[...]`.

Không có `skills_dir`, không có `harness_profile`. (Chữ ký runtime đầy đủ dán trong dev report.)

### 3.1. Thứ tự middleware được ráp (từ docstring, đã đối chiếu source `graph.py`)

> **Base stack:** `SkillsMiddleware` (nếu `skills` bật) → `FilesystemMiddleware` →
> `SubAgentMiddleware` (nếu có inline subagent) → **`SummarizationMiddleware`** →
> `PatchToolCallsMiddleware` → `AsyncSubAgentMiddleware` (nếu có async subagent)
> **→ [user middleware được chèn ở đây]** →
> **Tail stack:** profile `extra_middleware` → `_ToolExclusionMiddleware` (nếu có `excluded_tools`) →
> `AnthropicPromptCachingMiddleware` (no-op với model non-Anthropic) → `Bedrock/Fireworks` tương tự →
> `MemoryMiddleware` (nếu `memory` bật) → `HumanInTheLoopMiddleware` (nếu `interrupt_on`).

Sau khi ráp: profile `excluded_middleware` được lọc; `FilesystemMiddleware` và
`SubAgentMiddleware` nằm trong "protected scaffolding" KHÔNG được exclude.

### 3.2. Ý nghĩa tham số (rút gọn, xem docstring đầy đủ trong source)

- **model:** `BaseChatModel | provider:model string` (qua `init_chat_model`). `model=None` dùng mặc định
  `claude-sonnet-4-6` nhưng **deprecated từ 0.5.3**, bỏ trong 1.0.0 → **luôn truyền model**. Với model
  `openai:` mặc định dùng Responses API.
- **tools:** **cộng thêm** vào tool built-in mặc định = `ls, read_file, write_file, edit_file, glob, grep`
  (file ops) + `execute` (chạy shell) + `task` (gọi subagent). Không bao giờ bỏ built-in; muốn bỏ phải dùng
  `HarnessProfile(excluded_tools=...)` hoặc tự truyền `FilesystemMiddleware`.
- **system_prompt:** `USER` đặt đầu; prompt cuối ráp `USER -> BASE -> SUFFIX` (BASE/SUFFIX từ profile).
- **middleware:** user middleware chèn sau base stack, trước tail stack (xem thứ tự ở trên).
- **subagents:** 3 dạng `SubAgent` (declarative, qua tool `task`), `CompiledSubAgent` (runnable đã compile),
  `AsyncSubAgent` (remote/background). Nếu không có subagent tên `general-purpose`, mặc định thêm 1 cái
  (trừ khi profile tắt).
- **skills:** list **source path** POSIX tương đối với `root_dir` backend, vd `["/skills/user/", "/skills/project/"]`.
  Source sau **override** source trước khi trùng tên skill. (source có thể là `str` hoặc `(path, label)` tuple.)
- **memory:** list path file `AGENTS.md`, nạp **lúc khởi động, chèn tĩnh vào system prompt** (KHÔNG động).
  Display name tự suy từ path.
- **permissions:** list `FilesystemPermission` eval theo thứ tự, rule đầu thắng; mode `allow`/`deny`/`interrupt`.
- **backend:** instance `BackendProtocol` (vd `StateBackend()`). Muốn `execute` phải dùng backend implement
  `SandboxBackendProtocol`.
- **response_format:** structured output (ToolStrategy/ProviderStrategy/AutoStrategy/Pydantic type/dict).
- **checkpointer / store / debug / name / cache:** pass-through vào `create_agent`.

---

## 4. HEADLINE — execute/sandbox matrix (cho Task 2)

| Backend | `SandboxBackendProtocol`? | `execute` (shell) | Ghi chú |
|---|---|---|---|
| `StateBackend` | ❌ | **KHÔNG có** — tool `execute` trả lỗi | mặc định; không persistent |
| `FilesystemBackend` | ❌ | **KHÔNG có** | file trên đĩa, không shell |
| `StoreBackend` | ❌ | **KHÔNG có** | long-term memory qua Store |
| `CompositeBackend` | ❌ | **KHÔNG có** | ghép backend con — xem đường dẫn con |
| `LocalShellBackend` | ✅ | **CÓ** — shell **không bị cô lập** | `FilesystemBackend` + shell trực tiếp trên host |
| `BaseSandbox` (ABC) | ✅ | (abstract) | kế thừa để tự build sandbox cô lập |
| `LangSmithSandbox` | ✅ | CÓ | chạy qua LangSmith remote sandbox |

Nguồn: `backends/protocol.py` docstring nói rõ `StateBackend` và `StoreBackend` **không có `execute`**
("no process to exec into"); `FilesystemMiddleware` lọc tool `execute` ở call-time nếu backend không hỗ trợ.

**⇒ Khuyến nghị cho Task 2 (code-exec):** dev/test dùng **`LocalShellBackend`** (nhanh, nhưng
`⚠️ KHÔNG an toàn` — cần `interrupt_on` HITL hoặc môi trường dev cá biệt, đọc kỹ security warning);
production muốn code-exec phải **kế thừa `BaseSandbox`** để build sandbox cô lập. Các tool thực sự được
"exercised" khi backend hỗ trợ: `execute`; ngoài ra `ls/read_file/write_file/edit_file/glob/grep` chạy mọi nơi.

---

## 5. `StoreBackend` — signature thực tế (cho Task 5)

**Signature runtime** (đã dán đầy đủ trong dev report):

```python
def __init__(self, *, namespace: NamespaceFactory, store: BaseStore | None = None) -> None:
```

- `namespace` là **keyword-only**, `Callable[[Runtime], tuple[str, ...]]`.
- `store=None` → lấy store từ LangGraph execution context (`get_store()`) lúc graph chạy → **bắt buộc**
  truyền `store=` vào `create_deep_agent(...)`.
- Ví dụ namespace hợp lệ: `lambda rt: (rt.server_info.user.identity, "filesystem")`.

**⇒ Kiểm tra claim của plan** `StoreBackend(namespace=lambda runtime: ("memories", runtime.context.user_id))`:
- ✓ Đúng dạng: factory nhận `Runtime`, trả tuple. `Runtime` (từ `langgraph.runtime`) có field `context`
  (kiểu generic `ContextT`) và `server_info.user`.
- ⚠️ `runtime.context.user_id` chỉ tồn tại nếu bạn định nghĩa `context_schema` có field `user_id` và truyền
  `context_schema=` vào `create_deep_agent`. Nếu không, khi nào `_get_namespace()` gọi factory ngoài graph,
  hoặc `context.user_id` không tồn tại → runtime phải được resolve từ graph execution context.
- Cách đơn giản & an toàn nhất nếu cố định user: `StoreBackend(namespace=lambda _rt: ("memories", user_id))`
  (factory không cần đọc Runtime — ghi rõ trong docstring).

---

## 6. `CompositeBackend` — signature thực tế (cho Task 5)

```python
def __init__(self, default: BackendProtocol | StateBackend,
             routes: dict[str, BackendProtocol], *, artifacts_root: str = "/") -> None:
```

- **KHÁC claim của plan:** plan ví dụ `CompositeBackend({"/skills/": ..., "/memory/": ...})` truyền **1 positional
  dict** — **KHÔNG đúng**. Signature yêu cầu **2 tham số**: `default` (backend cho path không khớp route) +
  `routes` (dict path-prefix → backend).
- Đúng cú pháp: `CompositeBackend(default=FilesystemBackend(root_dir="."), routes={"/memory/": StoreBackend(...)})`.
- Prefix phải bắt đầu `"/"` và nên kết thúc `"/"` (vd `"/memories/"`). Routes được sắp xếp **dài nhất trước**
  để matching prefix chính xác.

---

## 7. `SummarizationMiddleware` — config (cho Task 3)

**`langchain.agents.middleware.SummarizationMiddleware.__init__`** (runtime):

```
(self, model, *, trigger=None, keep=('messages', 20), token_counter=count_tokens_approximately,
 summary_prompt=<DEFAULT_SUMMARY_PROMPT>, trim_tokens_to_summarize=4000, **deprecated_kwargs)
```

- `trigger` nhận tuple `("fraction", float)` | `("tokens", int)` | `("messages", int)` | `TriggerClause` | list.
- `keep` mặc định `("messages", 20)`.
- `token_counter` mặc định `count_tokens_approximately`; `trim_tokens_to_summarize` mặc định 4000.

**Xác nhận: `create_deep_agent` có thêm summarization mặc định KHÔNG? ⇒ CÓ.**
Nguồn `graph.py:840`: `deepagent_middleware.extend([create_summarization_middleware(model, backend),
PatchToolCallsMiddleware()])`. `create_summarization_middleware` (deepagents) auto-chọn trigger/keep
fraction-based từ profile model (`compute_summarization_defaults`). Muốn override: truyền
`middleware=[SummarizationMiddleware(...)]` đã cấu hình (chèn sau base stack theo mục 3.1).

---

## 8. `memory` param — xác nhận (cho Task 5)

- `memory=[...]` = list path file `AGENTS.md`; **nạp tĩnh lúc khởi động, chèn vào system prompt** qua
  `MemoryMiddleware` (graph.py:860-869, `sources=memory`, `add_cache_control=True`).
- Đây **KHÔNG phải** long-term memory động. **Long-term memory thật sự** = dùng **`store`** + `StoreBackend`
  (filesystem-as-memory, mục 5) hoặc **LangMem** (`create_memory_store_manager`).

---

## 9. `skills` param — progressive disclosure (cho Task 1)

- `skills=[...]` = list **source path** (POSIX), mỗi source là 1 thư mục chứa các skill-folder; mỗi skill-folder
  có `SKILL.md`. Nhiều source nạp theo thứ tự, source sau override trước (layer: base → team → project).
- Source có thể là `str` hoặc `(path, label)` tuple (`SkillSource`).
- Với `StateBackend` (mặc định): skill cung cấp qua `invoke(files={...})`. Với `FilesystemBackend`: load từ đĩa
  tương đối với `root_dir`.
- Progressive disclosure: chỉ **front-matter YAML** (`name` ≤64 ký tự thường+nằm ngang, `description` ≤1024
  char) được load mặc định; phần còn lại agent đọc khi cần.
- **KHÔNG có `skills_dir`** — bỏ claim đó; dùng `skills=[...]`.

---

## 10. DeepAgent prompts — built-in tool note (cho Task 2)

Mặc định agent có sẵn: `ls, read_file, write_file, edit_file, glob, grep` (file ops), `execute` (shell, chỉ
khi backend implement `SandboxBackendProtocol` — ngược lại trả lỗi), `task` (gọi subagent). `tools=[...]`
là **cộng thêm**, không thay thế built-in (đối chiếu docstring create_deep_agent).

---

## 11. langgraph-cli

- Cài được: **`langgraph-cli==0.4.31`** (cài qua `uv pip install --python .venv/bin/python langgraph-cli`).
- CLI có sẵn: `langgraph --help` hiện các lệnh `build`, `deploy`, `dev`, `dockerfile`, `new`, `up`, `validate`.
- ⇒ Ghi nhận: **đã cài & hoạt động** (Task 8 sẽ dùng `langgraph dockerfile` / `langgraph dev` / `langgraph up`).

---

## 12. Mâu thuẫn giữa plan brief & API thực tế (đã verify + sửa)

1. **`skills_dir` KHÔNG tồn tại** trong `create_deep_agent` → dùng `skills=[...]` (source paths). *(Plan 4.1 cũng ghi đúng ở Phase 1.)*
2. **`harness_profile` param KHÔNG tồn tại** trong `create_deep_agent` → profile được xử lý nội bộ (qua `register_harness_profile`),
   không phải param trực tiếp.
3. **`CompositeBackend` signature**: cần `(default, routes)` chứ **không** phải 1 positional dict như ví dụ plan (mục 6).
4. **`StoreBackend(namespace=...)`** là **keyword-only**, và `runtime.context.user_id` chỉ dùng được nếu bạn định nghĩa
   `context_schema` với field `user_id` (mục 5).
5. **`AsyncSubAgentMiddleware` và `RubricMiddleware` ⇒ TỒN TẠI** trong `__init__.py` (khớp brief).
6. **Summary mặc định**: brief Phase 3 nói "đã được thêm mặc định" — **đúng** (mục 7).
7. **`SkillsMiddleware` KHÔNG expose tool `list_skills`/`read_skill`** (Task 1 verify): skill được nạp vào
   `state["skills_metadata"]` và **chèn vào system prompt** (name+description+`Read <path>`), body đọc qua
   tool built-in **`read_file`** trên path `/skills/<name>/SKILL.md` — bằng đúng prompt hướng dẫn
   "progressive disclosure" của middleware (`middleware/skills.py:723`). Kèm ràng buộc `name` phải khớp tên
   thư mục chứa `SKILL.md` (`skills.py:349`). Với `StateBackend`, `invoke(files={"/skills/.../SKILL.md": create_file_data(content)})` — giá trị `files` là `FileData` dict, KHÔNG phải chuỗi trần (`state.py:359`).
