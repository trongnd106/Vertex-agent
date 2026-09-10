# Tool System

> **Nguồn tham khảo:** DeepAgents `middleware/filesystem.py`, `middleware/subagents.py`, `backends/sandbox.py`; LangGraph `prebuilt/tool_node.py`; orchestrator tool management (`utils.py`, MCP tools, tool categories)

## Mục tiêu

Xây dựng tool management system hoàn chỉnh: built-in tools, custom tools, MCP integration, sandbox execution, và permission system.

## Tasks

### Task 3.1: Built-in Filesystem Tools

**Mô tả:** Implement các built-in filesystem tools cho agent.

**File tham khảo:**
- DeepAgents: `middleware/filesystem.py` (ls, read_file, write_file, edit_file, glob, grep, execute, delete)
- `backends/protocol.py` (BackendProtocol)
- `backends/_fs_interrupt.py` (interrupt handling)

**Yêu cầu:**
- `ls` — list directory contents
- `read_file` — đọc file với offset/limit
- `write_file` — ghi file (tạo mới hoặc overwrite)
- `edit_file` — sửa file (find & replace)
- `delete` — xóa file
- `glob` — tìm file theo pattern
- `grep` — tìm nội dung trong file
- `execute` — chạy shell command (chỉ khi backend hỗ trợ)
- Large result eviction: tự động offload result >20K tokens
- Permission integration: allow/deny/interrupt per path

### Task 3.2: Custom Business Tools

**Mô tả:** Implement custom tools cho business logic (tool calling, tool chaining).

**File tham khảo:**
- orchestrator: `utils.py` tool handling, tool categories (task, plan, mcpserver, code_interpreter, ragflow_tool)
- DeepAgents: `_tools.py` tool overrides

**Yêu cầu:**
- Tool registry: đăng ký và quản lý custom tools
- Tool chaining: kết quả tool này là input tool khác
- Tool timeout: per-tool timeout configuration
- Tool retry: retry với exponential backoff
- Tool categories như orchestrator:
  - Task tool: gọi task definition
  - Plan tool: gọi plan từ bot khác
  - Code interpreter: Python sandbox
  - RAG tool: retrieval từ knowledge base

### Task 3.3: MCP Tool Integration

**Mô tả:** Tích hợp MCP (Model Context Protocol) tools vào agent system.

**File tham khảo:**
- orchestrator: MCP tool flow (`litellm_proxy_get_mcp_tool_meta`, `litellm_proxy_call_mcp`)
- DeepAgents: langchain-mcp-adapters integration
- LangGraph MCP adapters

**Yêu cầu:**
- MCP client: kết nối tới MCP servers qua stdio/SSE
- Tool discovery: fetch tools từ MCP server
- Tool name prefix: `mcp__server__{name}-{tool}`
- Tool execution: gọi MCP tool và parse kết quả
- MCP server lifecycle management: start/stop/restart
- Error handling: MCP server disconnect, timeout
- Multiple MCP servers: mỗi server cung cấp tool set riêng

### Task 3.4: Sandbox & Safe Execution

**Mô tả:** Implement sandbox execution environment cho code interpreter và shell commands.

**File tham khảo:**
- DeepAgents: `backends/sandbox.py` (BaseSandbox), `backends/local_shell.py` (LocalShellBackend), `backends/langsmith.py` (LangSmithSandbox)
- orchestrator: `python_executor.py`, `components/agent/deepagent/aio_sandbox.py`

**Yêu cầu:**
- BaseSandbox ABC: `execute`, `upload_files`, `download_files`, `id`
- LocalShellBackend cho dev (cảnh báo security)
- Python sandbox: restricted Python execution
- Container sandbox: Docker container per execution
- LangSmith sandbox: remote sandbox
- Resource limits: CPU, memory, timeout per command
- File transfer: upload/download files từ sandbox
- Network isolation: sandbox không truy cập network (tùy chọn)

### Task 3.5: Tool Permission & Audit System

**Mô tả:** Xây dựng permission system cho tools và audit logging.

**File tham khảo:**
- DeepAgents: `middleware/permissions.py`, `middleware/filesystem.py` FilesystemPermission
- orchestrator: security patterns

**Yêu cầu:**
- FilesystemPermission: `operations=["read","write"]`, `paths` (glob patterns), `mode="allow"|"deny"|"interrupt"`
- Tool-level permissions: tool nào được phép gọi
- Path-level permissions: file path nào được phép truy cập
- Role-based access: customer-support vs operator roles
- Human-in-the-loop: interrupt mode cho sensitive operations
- Audit logging: ghi log mọi tool execution: user, tool, args, result, timestamp
- Audit query API: tìm kiếm audit log theo user/tool/thời gian

### Task 3.6: Tool Description & Discovery

**Mô tả:** Xây dựng system cho tool descriptions, discovery và dynamic tool selection.

**File tham khảo:**
- DeepAgents: `profiles/harness/harness_profiles.py` tool_description_overrides
- orchestrator: `components/agent/deepagent/middleware/tool_selection.py`

**Yêu cầu:**
- Tool description overrides: mô tả tool ngắn gọn, rõ ràng cho LLM
- Tool discovery: agent có thể tìm tool theo tên/mô tả
- Dynamic tool selection: chọn tools dựa trên context và user query
- Tool usage statistics: tool nào được dùng nhiều, hiệu quả
- Tool documentation generation: tự động sinh doc từ tool definitions
- Tool cost tracking: token cost per tool execution