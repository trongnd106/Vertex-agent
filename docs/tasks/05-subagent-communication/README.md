# Subagent & Communication

> **Nguồn tham khảo:** DeepAgents `middleware/subagents.py`, `middleware/async_subagents.py`; orchestrator subagent patterns (SubAgent, CompiledSubAgent, AsyncSubAgent); LangGraph subgraph patterns + remote execution

## Mục tiêu

Xây dựng hệ thống subagent communication cho phép agent spawning subagents (sync/async), inter-agent communication, và parallel task execution.

## Tasks

### Task 5.1: Synchronous Subagent System

**Mô tả:** Implement synchronous subagent system: main agent spawn subagent và chờ kết quả.

**File tham khảo:**
- DeepAgents: `middleware/subagents.py` (SubAgentMiddleware, SubAgent, CompiledSubAgent)
- orchestrator: subagent patterns

**Yêu cầu:**
- SubAgent types:
  - **SubAgent**: declarative spec với name, description, system_prompt, model, tools, middleware
  - **CompiledSubAgent**: pre-compiled Runnable
- `task` tool: cho main agent gọi subagent
- Subagent propagation: main -> subagent key fields
- Context isolation: subagent có state riêng, không merge vào main
- Result return: ToolMessage(content=...) với full result
- Default general-purpose subagent

### Task 5.2: Asynchronous Subagent System

**Mô tả:** Implement asynchronous subagent system: background subagents chạy trên remote deployment.

**File tham khảo:**
- DeepAgents: `middleware/async_subagents.py` (AsyncSubAgentMiddleware, AsyncSubAgent)
- LangGraph SDK: remote execution patterns

**Yêu cầu:**
- AsyncSubAgent: `graph_id`, `url`, `headers` — remote LangGraph deployment
- Async lifecycle tools:
  - `launch_task` — tạo thread + run mới trên remote server
  - `update_task` — push HumanMessage vào thread
  - `cancel_task` — interrupt run
  - `get_task_status` — poll trạng thái
  - `list_tasks` — liệt kê tasks đang chạy
- Background execution: không block main agent
- Result polling: periodic check cho kết quả

### Task 5.3: Inter-agent Communication Protocol

**Mô tả:** Xây dựng communication protocol giữa các agents: message passing, events, và data sharing.

**File tham khảo:**
- orchestrator: event system (EventToTriggerTask), message broker (Kafka/ActiveMQ)
- DeepAgents: subagent result patterns
- LangGraph: Command(graph=Command.PARENT) for subgraph-parent communication

**Yêu cầu:**
- Message passing: agent -> agent messages
- Event system: events như exception-based communication
- Shared state: agents có thể đọc/ghi shared store
- Parent-child: subagent gửi kết quả và state updates về main
- Sibling agents: agents cùng level giao tiếp qua store/events
- Remote agents: communication qua MCP hoặc LangGraph SDK
- Message broker integration: Kafka/ActiveMQ cho cross-service

### Task 5.4: Parallel Tool Execution (AgentExecutor)

**Mô tả:** Implement parallel tool execution system: execute nhiều tool calls concurrently.

**File tham khảo:**
- orchestrator: `task_manager.py`, AgentExecutor (`execute_agentexecutor_task`)
- LangGraph: parallel execution patterns

**Yêu cầu:**
- ThreadPool-based: submit tools vào ThreadPool, chờ tất cả hoàn thành
- Worker pool: max N workers (configurable, default 3)
- Tool types hỗ trợ: `tool`, `plan`, `mcpserver`, `code_interpreter`, `ragflow_tool`
- Result collection: collect all results, build tool responses
- Error isolation: 1 tool fail không ảnh hưởng tools khác
- Timeout: per-tool timeout
- Stream support: emit results khi từng tool hoàn thành

### Task 5.5: Subagent Profile & Resource Management

**Mô tả:** Quản lý subagent profiles, resources, và lifecycle.

**File tham khảo:**
- DeepAgents: `profiles/harness/harness_profiles.py` (HarnessProfile for subagents)
- orchestrator: subagent config patterns

**Yêu cầu:**
- Subagent profiles: reusable subagent configurations
  - `GeneralPurposeSubagentProfile`: model, prompt, tool visibility defaults
- Resource limits:
  - Max subagents per turn
  - Max concurrent async subagents
  - Token budget per subagent
  - Timeout per subagent execution
- Lifecycle management:
  - Subagent creation -> execution -> result collection -> cleanup
  - Orphan detection: async subagents bị abandoned
  - Force terminate: kill subagent khi timeout
- Profile inheritance: subagent kế thừa profile từ parent agent