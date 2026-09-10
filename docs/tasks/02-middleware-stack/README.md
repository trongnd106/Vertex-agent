# Middleware Stack

> **Nguồn tham khảo:** DeepAgents `middleware/` (15 modules), chatbot-orchestrator `components/agent/deepagent/middleware/` (15+ modules), LangChain `agents/middleware/types.py` (AgentMiddleware abstraction)

## Mục tiêu

Xây dựng middleware pipeline theo Chain-of-Responsibility pattern. Middleware stack cho phép intercept model requests/responses, inject tools, modify state, và thêm cross-cutting concerns.

## Tasks

### Task 2.1: AgentMiddleware Base Class

**Mô tả:** Implement AgentMiddleware abstract base class với lifecycle hooks.

**File tham khảo:**
- LangChain: `agents/middleware/types.py` (AgentMiddleware)
- DeepAgents: `middleware/__init__.py`

**Yêu cầu:**
- Base class AgentMiddleware với:
  - `name`: str — unique identifier
  - `state_schema`: type | None — optional state fields
  - `tools`: list[BaseTool] — tools contributed
  - `system_prompt`: str | None — system prompt injection
- Lifecycle hooks:
  - `before_agent(state, runtime, config)` — chạy trước agent execution
  - `after_agent(state, runtime, config)` — chạy sau agent execution
  - `wrap_model_call(request, handler)` — intercept model request (sync)
  - `awrap_model_call(request, handler)` — intercept model request (async)
  - `modify_request(request)` — modify request trước khi gửi đến model
  - `before_model(model, config)` — chạy trước model inference
- Middleware ordering: thứ tự quyết định priority

### Task 2.2: Middleware Stack Builder

**Mô tả:** Xây dựng middleware stack builder: assemble, validate, và quản lý middleware ordering.

**File tham khảo:**
- DeepAgents: `graph.py` middleware assembly logic (~line 800-900)
- chatbot-orchestrator: `components/agent/deepagent/graph.py` middleware stack ordering

**Yêu cầu:**
- Middleware stack assembly với 3 segment:
  - **Base stack**: TodoList -> Skills -> Filesystem -> SubAgent -> Summarization -> PatchToolCalls -> AsyncSubAgent
  - **Caller middlewares**: user-provided middlewares
  - **Tail stack**: profile extra_middleware -> PromptCaching -> Memory -> HumanInTheLoop
- Middleware merge strategy: replace by name vs append
- Middleware exclusion: profile excluded_middleware
- Middleware validation: circular dependency, type checking
- `create_middleware_stack()` factory function

### Task 2.3: Summarization Middleware

**Mô tả:** Implement SummarizationMiddleware: tự động compact conversation khi token usage vượt ngưỡng.

**File tham khảo:**
- DeepAgents: `middleware/summarization.py`
- chatbot-orchestrator: `components/agent/deepagent/middleware/summarization.py`

**Yêu cầu:**
- Trigger modes: `fraction` (tỷ lệ context window), `absolute` (số token cụ thể), `messages` (số message)
- Keep window: giữ N messages gần nhất
- Offload history vào backend file (như DeepAgents `/conversation_history/`)
- Media handling: tách base64 media ra riêng
- `compact_conversation` tool cho manual trigger
- Token counting: `count_tokens_approximately`
- Anthropic prompt caching support

### Task 2.4: Rubric/Self-Evaluation Middleware

**Mô tả:** Implement RubricMiddleware: self-evaluation và grading cho agent output.

**File tham khảo:**
- DeepAgents: `middleware/rubric.py`
- chatbot-orchestrator: rubric-like patterns

**Yêu cầu:**
- Define rubric với các criteria (identity/critical/simple)
- Grader sub-agent để chấm điểm output
- Revision loop: nếu fail rubric -> feedback -> revision
- Nested rubric: parent rubric cho sub-agent output
- Configurable passing threshold
- Streaming support cho grader feedback

### Task 2.5: Tool Calling Middleware

**Mô tả:** Xây dựng middleware cho tool calling: interception, patching, permissions, và exclusion.

**File tham khảo:**
- DeepAgents: `middleware/patch_tool_calls.py`, `middleware/permissions.py`, `middleware/_tool_exclusion.py`
- chatbot-orchestrator: `components/agent/deepagent/middleware/tooling.py`, `tool_call_limit.py`, `tool_selection.py`

**Yêu cầu:**
- **PatchToolCallsMiddleware**: sửa lỗi JSON, thêm fields thiếu, batch fix
- **ToolingMiddleware**: quản lý tool registry, quyết định tool nào enabled
- **PermissionsMiddleware**: FilesystemPermission rules (allow/deny/interrupt)
- **ToolExclusionMiddleware**: HarnessProfile excluded_tools
- **ToolCallLimitMiddleware**: giới hạn số tool calls per turn
- **ToolSelectionMiddleware**: lọc tools dựa trên context

### Task 2.6: Progress & Streaming Middleware

**Mô tả:** Xây dựng middleware cho progress tracking và streaming state updates.

**File tham khảo:**
- chatbot-orchestrator: `components/agent/deepagent/middleware/first_middleware.py`, `agent_current_state.py`, `todo.py`, `last_middleware.py`

**Yêu cầu:**
- **FirstMiddleware**: gửi thông điệp khởi tạo, set session markers
- **AgentCurrentStateMiddleware**: track trạng thái agent hiện tại
- **TodoListMiddleware**: `write_todos` tool cho agent task list
- **ProgressMiddleware**: emit progress events qua streaming pipeline
- **LastMiddleware**: finalize stream, gửi thông điệp kết thúc
- Show_progress callback integration

### Task 2.7: PII & Security Middleware

**Mô tả:** Xây dựng middleware cho PII redaction và security checks.

**File tham khảo:**
- chatbot-orchestrator: `components/agent/deepagent/middleware/pii.py`, `pia.py`
- DeepAgents: `backends/local_shell.py` security warnings

**Yêu cầu:**
- **PIIMiddleware**: phát hiện và redact PII (email, SĐT, CMND, etc.)
- **PIAMiddleware**: kiểm tra PIA trước khi thực thi tool
- **SecurityMiddleware**: input validation, injection prevention
- **AuditMiddleware**: audit logging cho mọi tool execution
- Configurable PII patterns (regex-based)
- Model-based PII detection cho patterns khó