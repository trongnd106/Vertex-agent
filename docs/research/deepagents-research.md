# Research: DeepAgents Library Architecture

## 1. Tong Quan Cau Truc Thu Muc

```
deepagents/
  libs/
    deepagents/          -- Core library (Python package)
      deepagents/
        graph.py                    -- Assembly point: create_deep_agent()
        __init__.py                 -- Public API exports
        _tools.py                   -- Tool description override helpers
        _models.py                  -- Model resolution (provider:model -> BaseChatModel)
        _messages_reducer.py        -- DeltaChannel reducer for messages
        _excluded_middleware.py     -- Profile-based middleware exclusion logic
        _version.py                 -- Version string
        
        backends/                   -- Pluggable storage/execution backends
          protocol.py               -- BackendProtocol ABC, dataclasses (ReadResult, WriteResult, etc.)
          state.py                  -- StateBackend (ephemeral, in-agent-state)
          filesystem.py             -- FilesystemBackend (real disk I/O)
          local_shell.py            -- LocalShellBackend (shell execution)
          store.py                  -- StoreBackend (LangGraph BaseStore-backed)
          composite.py              -- CompositeBackend (route-based multiplexing)
          context_hub.py            -- ContextHubBackend
          langsmith.py              -- LangSmithSandbox
          sandbox.py                -- BaseSandbox
          utils.py                  -- Shared utilities (path validation, grep, file type detection)

        middleware/                 -- AgentMiddleware implementations
          __init__.py               -- Exports all middleware
          filesystem.py             -- FilesystemMiddleware (ls, read/write/edit, glob, grep, execute tools)
          subagents.py              -- SubAgentMiddleware (task tool for synchronous subagents)
          async_subagents.py        -- AsyncSubAgentMiddleware (remote/background subagents)
          memory.py                 -- MemoryMiddleware (AGENTS.md memory loading)
          skills.py                 -- SkillsMiddleware (on-demand skill workflows)
          summarization.py          -- SummarizationMiddleware (automatic context compaction)
          rubric.py                 -- RubricMiddleware (self-evaluation grader loop)
          permissions.py            -- Permissions middleware
          patch_tool_calls.py       -- PatchToolCallsMiddleware
          _message_eviction.py      -- Large tool result offloading
          _overflow_clip.py         -- Context overflow clipping
          _state.py                 -- Private state field helpers
          _tool_exclusion.py        -- Tool exclusion logic
          _utils.py                 -- Shared middleware utilities
          _video.py                 -- Video frame extraction
          _fs_interrupt.py          -- Filesystem interrupt config builder
          _excluded_middleware.py    -- (high-level) Exclusion application

        profiles/                   -- Provider/Harness profiles
          harness/                  -- HarnessProfile (prompt, tool visibility, subagent defaults)
          provider/                 -- ProviderProfile (model construction overrides)
          _builtin_profiles.py
          _keys.py

        _api/
          deprecation.py            -- Deprecation warning utilities

    cli/                            -- CLI tool
    code/                           -- Code analysis tools
    acp/                            -- Agent Communication Protocol
    talon/                          -- Talon integration
    evals/                          -- Evaluation framework
    partners/                       -- Partner integrations

  examples/                         -- Example applications
  AGENTS.md                         -- Agent memory specification
  action.yml                        -- GitHub Action config
```

---

## 2. Cac Module / Core Concepts Chinh

### 2.1 Agent (create_deep_agent)
File: `libs/deepagents/deepagents/graph.py`

Ham `create_deep_agent()` la entry point chinh. No nhan vao:
- **model**: `str` (dang `provider:model`) hoac `BaseChatModel` instance
- **tools**: danh sach tool tuy chinh
- **middleware**: middleware bo sung
- **subagents**: danh sach SubAgent / CompiledSubAgent / AsyncSubAgent
- **skills**: danh sach duong dan den skill directory
- **memory**: danh sach duong dan den AGENTS.md files
- **permissions**: FilesystemPermission rules
- **backend**: BackendProtocol instance
- **interrupt_on**: Human-in-the-loop config
- **response_format**: Structured output schema
- **state_schema**: Custom state schema (ke thua DeepAgentState)
- **checkpointer / store / debug / name / cache**: LangGraph params

Assembly flow:
1. Resolve model -> xac dinh HarnessProfile phu hop
2. Resolve backend (default: `StateBackend()`)
3. Xu ly subagents: phan loai inline (SubAgent/CompiledSubAgent) vs async (AsyncSubAgent)
4. Build middleware stack (base -> caller -> tail)
5. Assemble system prompt (prefix -> base -> suffix -> profile suffix)
6. Goi LangChain `create_agent()` -> nhan ve `CompiledStateGraph`
7. Tra ve agent graph co config (recursion_limit=9999, metadata...)

### 2.2 Tool
File: `libs/deepagents/deepagents/_tools.py` + `middleware/filesystem.py`
File: `middleware/subagents.py` (task tool)

Tools duoc cung cap tu 2 nguon:
1. **SDK middleware**: FilesystemMiddleware cung cap cac tool built-in:
   - `ls`, `read_file`, `write_file`, `edit_file`, `delete` (filesystem ops)
   - `glob`, `grep` (search)
   - `execute` (shell commands, chi khi backend ho tro)
   - `task` (subagent delegation, tu SubAgentMiddleware)
2. **Consumer-provided tools**: tools truyen vao `tools=` parameter

Moi tool la `StructuredTool.from_function()` voi sync + async wrappers.

### 2.3 Memory
File: `middleware/memory.py`

`MemoryMiddleware` load noi dung tu AGENTS.md files (xem [agents.md](https://agents.md/)) va inject vao system prompt. No dung `before_agent` hook de load files tu backend, luu vao `state.memory_contents` (PrivateStateAttr), sau do `modify_request` chen vao system message template.

### 2.4 Planning / Todo
File: tu `langchain.agents.middleware.TodoListMiddleware`

Todo list middleware (tu LangChain core) cho phep agent quan ly task list voi `write_todos` tool.

### 2.5 Skills
File: `middleware/skills.py`

`SkillsMiddleware` load skill definitions tu backend sources. Skills la cac directory chua `SKILL.md` voi YAML frontmatter. Dung progressive disclosure: chi hien thi skills khi duoc goi.

### 2.6 SubAgents
File: `middleware/subagents.py`

Co 3 loai subagent:
- **SubAgent**: Declarative spec (name, description, system_prompt, tools, model, middleware...)
- **CompiledSubAgent**: Pre-compiled Runnable (tu create_agent hoac custom LangGraph graph)
- **AsyncSubAgent**: Remote subagent chay tren LangGraph Platform server (qua LangGraph SDK)

SubAgentMiddleware tao `task` tool de main agent goi subagent. Subagent duoc isolate context rieng, tra ve 1 ToolMessage duy nhat.

### 2.7 Rubric (Self-Evaluation)
File: `middleware/rubric.py`

`RubricMiddleware` cho phep caller dinh nghia tieu chi danh gia (rubric). Khi agent tra loi xong, middleware goi mot grader sub-agent de cham diem. Neu can revision, feedback duoc inject lam HumanMessage va vong lap tiep tuc.

### 2.8 Summarization
File: `middleware/summarization.py`

`SummarizationMiddleware` tu dong compact conversation khi token usage vuot nguong. No summary tin nhan cu bang LLM call, offload history sang backend. Co 2 trigger mode: `fraction` (ty le context window) va `absolute` (so token cu the).

---

## 3. Design Patterns Duoc Su Dung

### 3.1 Middleware / Pipeline Pattern
Toan bo agent behavior duoc xay dung xung quanh **middleware stack**. Moi middleware:
- Implement `AgentMiddleware` abstract class
- Override `wrap_model_call()` (sync) va `awrap_model_call()` (async) de **intercept model requests**
- Co the implement `before_agent` / `abefore_agent` de chay truoc agent execution
- Co the implement `modify_request` de sua doi request truoc khi gui den model
- Co the contribute tools (`self.tools`) va system prompt fragments
- Co the contribute state fields (`state_schema`)
- Order: base scaffolding -> caller middleware -> profile/tail middleware

### 3.2 Strategy Pattern (Backend Protocol)
`BackendProtocol` dinh nghia interface thong nhat cho file operations:
```python
class BackendProtocol(abc.ABC):
    def ls(self, path) -> LsResult
    def read(self, file_path, offset, limit) -> ReadResult
    def write(self, file_path, content) -> WriteResult
    def edit(self, file_path, old_string, new_string) -> EditResult
    def delete(self, file_path) -> DeleteResult
    def glob(self, pattern, path) -> GlobResult
    def grep(self, pattern, path, glob) -> GrepResult
```
Cac implementation: StateBackend, FilesystemBackend, StoreBackend, CompositeBackend, LangSmithSandbox.

### 3.3 Composite Pattern (CompositeBackend)
`CompositeBackend` cho phep route path prefix den cac backend khac nhau:
```python
backend = CompositeBackend(
    default=StateBackend(),
    routes={"/memories/": StoreBackend(store=my_store)},
)
```

### 3.4 Factory Pattern
- `BackendFactory`: backend co the la instance hoac callable factory
- `create_summarization_middleware()`: factory cho summarization middleware stack
- `register_provider_profile()` / `register_harness_profile()`: registry pattern

### 3.5 Registry Pattern (Profiles)
Harness profiles va Provider profiles duoc dang ky vao registry, tu dong ap dung cho model/provider phu hop:
```python
register_harness_profile("anthropic:claude-sonnet-4-6", my_profile)
register_provider_profile("openai:", my_provider_profile)
```

### 3.6 TypedDict / Dataclass Protocols
Su dung `TypedDict` cho state schemas va configs (`SubAgent`, `DeepAgentState`, `SystemPromptConfig`) va `@dataclass` cho result types (`ReadResult`, `WriteResult`, `GrepResult`...).

### 3.7 Adapter Pattern (Provider Profiles)
`ProviderProfile` chuyen doi provider-specific initialization params thanh LangChain-compatible kwargs:
```python
# OpenAI: mac dinh dung Responses API
# NVIDIA: them attribution headers
# OpenRouter: them app headers
```

### 3.8 Command Pattern (LangGraph Command)
Subagent middleware dung `Command(update=...)` de tra ve state updates tu tool functions.

---

## 4. Agent Communication / Tool Calling

### 4.1 Tool Calling Flow

```
Model Request
  |
  v
[Middlewares] -- Moi middleware co the:
  |              - Them/xoa tools khoi request
  |              - Inject system prompt text
  |              - Transform messages
  |              - Track cross-turn state
  v
Model (LLM) -- Tra ve text + tool_calls
  |
  v
Tool Execution
  |  - Built-in tools (filesystem, execute, task)
  |  - Custom tools (tu consumer)
  v
[Middlewares] -- Post-processing (summarization, rubric)
  |
  v
State Update (messages appended)
  |
  v
Return to Model hoac Final Response
```

### 4.2 Subagent Communication (synchronous)

```
Main Agent
  |
  |-- task(description, subagent_type)
  |     |
  |     v
  |   SubAgentMiddleware._build_task_tool()
  |     |
  |     |-- Locate compiled subagent by name
  |     |-- Prepare state: strip private + excluded keys
  |     |-- Inject HumanMessage(description) as subagent input
  |     |-- Invoke subagent (sync: .invoke(), async: .ainvoke())
  |     |
  |     v
  |   Subagent runs autonomously (full agent loop)
  |     |
  |     v
  |   Post-process result:
  |     - structured_response != None -> JSON serialize
  |     - else -> last AIMessage text
  |     - Return Command(update={messages: [ToolMessage]})
  |
  v
Main Agent receives ToolMessage(result)
```

### 4.3 Async Subagent Communication (remote)

Qua LangGraph SDK:
- `launch_task`: tao thread + run moi tren remote server
- `update_task`: push HumanMessage vao thread
- `cancel_task`: interrupt run
- `get_task_status`: poll trang thai
- `list_tasks`: liet ke cac task dang chay

### 4.4 Tool Permission System

```python
FilesystemPermission(
    operations=["read", "write"],
    paths=["/secrets/**", "/config/*"],
    mode="deny"  # hoac "allow", "interrupt"
)
```
- First-match wins
- "interrupt" mode auto-cai HumanInTheLoopMiddleware
- Apdung cho built-in filesystem tools (khong ap dung cho backend truc tiep)

---

## 5. Memory / Persistence Management

### 5.1 Agent State Persistence (LangGraph Checkpoints)
- Graph state duoc checkpointed sau moi step (neu co checkpointer)
- `DeepAgentState` dung `DeltaChannel` reducer de toi uu checkpoint growth (O(N) thay vi O(N^2))
- Checkpoints cho phep resume conversation, interrupt handling

### 5.2 File Storage (Backends)

| Backend | Storage Location | Persistence |
|---------|-----------------|-------------|
| StateBackend | LangGraph state (in-memory, checkpointed) | Trong 1 thread, khong cross-thread |
| FilesystemBackend | Disk (thu muc that) | Persistent |
| StoreBackend | LangGraph BaseStore | Persistent (cross-thread) |
| CompositeBackend | Route-based multiplexing | Linh hoat |
| LangSmithSandbox | LangSmith sandbox | Remote |

### 5.3 Memory System (AGENTS.md)
- `MemoryMiddleware` load files tu backend paths
- Luu vao `state.memory_contents` (PrivateStateAttr)
- Inject vao system prompt o moi turn qua `modify_request`
- Ho tro `cache_control: ephemeral` cho Anthropic prompt caching
- HTML comments (`<!-- -->`) tu dong stripped

### 5.4 Large Result Eviction
- `FilesystemMiddleware` tu dong offload large tool results (>20K tokens) vao backend
- Thay the bang preview + file_path reference
- HumanMessages >50K tokens cung duoc evicted
- Luu tru tai: `/<artifacts_root>/large_tool_results/<tool_call_id>`

### 5.5 Conversation Summarization
- `SummarizationMiddleware` tu dong trigger khi context day
- Offload history vao `/conversation_history/<thread_id>.md`
- Media (base64) duoc tach rieng vao `/conversation_history/media/`
- Co the trigger manual qua `compact_conversation` tool

---

## 6. Interfaces / Abstractions Quan Trong

### 6.1 AgentMiddleware (abstract)
File: `langchain.agents.middleware.types.AgentMiddleware`
```python
class AgentMiddleware:
    name: str                                   # Unique identifier
    state_schema: type | None                   # Optional state fields
    tools: list[BaseTool]                       # Tools contributed
    system_prompt: str | None                   # System prompt injection
    
    def before_agent(self, state, runtime, config) -> StateUpdate | None
    def abefore_agent(self, ...) -> StateUpdate | None
    def wrap_model_call(self, request, handler) -> ModelResponse
    def awrap_model_call(self, request, handler) -> ModelResponse
    def modify_request(self, request) -> ModelRequest
```

### 6.2 BackendProtocol (abstract)
File: `backends/protocol.py`
```python
class BackendProtocol(abc.ABC):
    def ls(self, path) -> LsResult
    def als(self, path) -> LsResult  # async
    def read(self, file_path, offset, limit) -> ReadResult
    def aread(self, ...) -> ReadResult
    def write(self, file_path, content) -> WriteResult
    def awrite(self, ...) -> WriteResult
    def edit(self, file_path, old_string, new_string, replace_all) -> EditResult
    def aedit(self, ...) -> EditResult
    def delete(self, file_path) -> DeleteResult
    def adelete(self, ...) -> DeleteResult
    def glob(self, pattern, path) -> GlobResult
    def aglob(self, ...) -> GlobResult
    def grep(self, pattern, path, glob, max_count) -> GrepResult
    def agrep(self, ...) -> GrepResult
    def download_files(self, paths) -> list[FileDownloadResponse]
    def adownload_files(self, paths) -> list[FileDownloadResponse]
    def upload_files(self, files) -> list[FileUploadResponse]
    def aupload_files(self, files) -> list[FileUploadResponse]
```

### 6.3 SandboxBackendProtocol (abstract)
File: `backends/protocol.py`
```python
class SandboxBackendProtocol(abc.ABC):
    def execute(self, command, timeout) -> ExecuteResult
    def aexecute(self, command, timeout) -> ExecuteResult
```
Extends BackendProtocol. Mac dinh check `isinstance(backend, SandboxBackendProtocol)` de quyet dinh co expose `execute` tool hay khong.

### 6.4 DeepAgentState
File: `graph.py`
```python
class DeepAgentState(AgentState):
    messages: Annotated[list[AnyMessage], DeltaChannel(_messages_delta_reducer, snapshot_frequency=50)]
```
Ke thua LangChain's AgentState, dung DeltaChannel de toi uu checkpoint.

### 6.5 SubAgent / CompiledSubAgent / AsyncSubAgent (TypedDicts)
File: `middleware/subagents.py`, `middleware/async_subagents.py`
```python
class SubAgent(TypedDict):
    name: str
    description: str
    system_prompt: str
    tools: NotRequired[...]
    model: NotRequired[...]
    middleware: NotRequired[...]
    interrupt_on: NotRequired[...]
    skills: NotRequired[...]
    permissions: NotRequired[...]
    response_format: NotRequired[...]

class CompiledSubAgent(TypedDict):
    name: str
    description: str
    runnable: Runnable

class AsyncSubAgent(TypedDict):
    name: str
    description: str
    graph_id: str
    url: NotRequired[str]
    headers: NotRequired[dict]
```

### 6.6 HarnessProfile
File: `profiles/harness/harness_profiles.py`
```python
@dataclass
class HarnessProfile:
    base_system_prompt: str | None     # Override base prompt
    system_prompt_suffix: str | None   # Append after system prompt
    excluded_tools: list[str]          # Tools to hide
    excluded_middleware: list[str | type]  # Middleware to remove
    extra_middleware: list[AgentMiddleware | Callable]
    tool_description_overrides: dict[str, str]
    general_purpose_subagent: GeneralPurposeSubagentProfile | None
```

### 6.7 ProviderProfile
File: `profiles/provider/provider_profiles.py`
```python
@dataclass
class ProviderProfile:
    model_matcher: Callable[[str], bool]  # Match provider:model pattern
    init_kwargs: dict[str, Any]           # Extra init params
    order: int                            # Priority ordering
```

### 6.8 ModelRequest / ModelResponse
File: `langchain.agents.middleware.types`
```python
@dataclass
class ModelRequest:
    messages: list[AnyMessage]
    system_message: SystemMessage | None
    tools: list[BaseTool]
    model: BaseChatModel
    state: AgentState
    context: ContextT | None
    
    def override(self, ...) -> ModelRequest

@dataclass
class ModelResponse:
    messages: list[AnyMessage]
    state: AgentState
```

---

## 7. Key Data Flow Diagram

```
create_deep_agent()
  |
  |-- resolve_model() -> BaseChatModel
  |-- resolve HarnessProfile for model
  |-- resolve Backend (default: StateBackend)
  |-- process subagents (build middleware stacks)
  |-- assemble main middleware stack:
  |     1. TodoListMiddleware
  |     2. SkillsMiddleware (if skills provided)
  |     3. FilesystemMiddleware
  |     4. SubAgentMiddleware (if inline subagents)
  |     5. SummarizationMiddleware
  |     6. PatchToolCallsMiddleware
  |     7. AsyncSubAgentMiddleware (if async subagents)
  |     8. [User middleware]
  |     9. [HarnessProfile extra middleware]
  |    10. PromptCachingMiddlewares
  |    11. MemoryMiddleware (if memory provided)
  |    12. HumanInTheLoopMiddleware (if interrupt_on)
  |-- assemble system prompt (prefix -> base -> suffix -> profile suffix)
  |-- LangChain create_agent() -> CompiledStateGraph
  |
  v
Agent Graph (LangGraph)
  |
  |-- Step 1: before_agent (all middleware) -> load memory, skills...
  |-- Step 2: wrap_model_call chain -> modify request
  |-- Step 3: Model inference (LLM)
  |-- Step 4: Tool execution (built-in + custom)
  |-- Step 5: Post-processing (summarization, rubric)
  |-- Step 6: State update + checkpoint
  |-- Repeat Step 2-6 until final response
```

---

## 8. Cac File Quan Trong Nhat Can Doc

| File | Muc dich |
|------|----------|
| `libs/deepagents/deepagents/graph.py` | Assembly point: `create_deep_agent()` |
| `libs/deepagents/deepagents/middleware/__init__.py` | Overview + middleware vs tool distinction |
| `libs/deepagents/deepagents/middleware/subagents.py` | SubAgent specification, task tool, SubAgentMiddleware |
| `libs/deepagents/deepagents/middleware/filesystem.py` | FilesystemMiddleware (full tool set) |
| `libs/deepagents/deepagents/middleware/memory.py` | MemoryMiddleware (AGENTS.md) |
| `libs/deepagents/deepagents/middleware/skills.py` | SkillsMiddleware |
| `libs/deepagents/deepagents/middleware/summarization.py` | SummarizationMiddleware |
| `libs/deepagents/deepagents/middleware/rubric.py` | RubricMiddleware (self-evaluation) |
| `libs/deepagents/deepagents/middleware/async_subagents.py` | AsyncSubAgentMiddleware |
| `libs/deepagents/deepagents/backends/protocol.py` | BackendProtocol, SandboxBackendProtocol, data types |
| `libs/deepagents/deepagents/backends/state.py` | StateBackend (ephemeral) |
| `libs/deepagents/deepagents/backends/filesystem.py` | FilesystemBackend (disk) |
| `libs/deepagents/deepagents/backends/composite.py` | CompositeBackend (route-based) |
| `libs/deepagents/deepagents/backends/store.py` | StoreBackend (BaseStore) |
| `libs/deepagents/deepagents/profiles/harness/harness_profiles.py` | HarnessProfile |
| `libs/deepagents/deepagents/profiles/provider/provider_profiles.py` | ProviderProfile |
| `libs/deepagents/deepagents/_models.py` | Model resolution helpers |
| `libs/ARCHITECTURE.md` | Official architecture document |