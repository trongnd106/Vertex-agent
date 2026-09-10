# Routing & Control Flow

> **Nguồn tham khảo:** LangGraph `graph/_branch.py` (BranchSpec), `graph/state.py` (StateGraph edges), `types.py` (Send, Command, Interrupt); chatbot-orchestrator `task_engine.py` (dispatch flow, event handling)

## Mục tiêu

Xây dựng routing và control flow system: conditional routing, loops, human-in-the-loop, error events, và flow control.

## Tasks

### Task 7.1: Conditional & Dynamic Routing

**Mô tả:** Implement conditional và dynamic routing cho agent graph.

**File tham khảo:**
- LangGraph: `graph/_branch.py` (BranchSpec, add_conditional_edges)
- `types.py` (Send, Command)

**Yêu cầu:**
- Conditional edges: `add_conditional_edges(source, router, path_map)`
- Router function: nhận state, trả về tên node đích
- Path map: dict mapping result -> node name
- Dynamic routing via Send: `Send("node_name", state)` từ node execution
- Command routing: `Command(goto="node_name")`, `Command(goto=Send(...))`
- Map-reduce: 1 node fan-out to multiple parallel nodes
- BranchSpec: path function + path_map -> trigger target nodes

### Task 7.2: Loops & Recursion

**Mô tả:** Implement loops và recursion control trong agent graph.

**File tham khảo:**
- LangGraph: Pregel recursion_limit, `pregel/main.py` loop handling

**Yêu cầu:**
- Recursion limit: max số bước agent execution (configurable, default 9999)
- Loop detection: phát hiện infinite loops
- For loop: fixed iteration count
- While loop: condition-based iteration
- Map loop: iterate over list items
- Nested loops: loops trong subgraphs
- Break/continue: loop control commands

### Task 7.3: Human-in-the-Loop

**Mô tả:** Implement human-in-the-loop mechanism: interrupt/resume, approval, và input collection.

**File tham khảo:**
- LangGraph: `types.py` (Interrupt), `graph/state.py` interrupt handling, `pregel/main.py` resume logic
- DeepAgents: HumanInTheLoopMiddleware, FilesystemMiddleware interrupt mode
- chatbot-orchestrator: Headless Tools Middleware (`ask_user_input_v0`), interrupt patterns

**Yêu cầu:**
- Interrupt mechanism: `interrupt(value)` -> pause execution, save checkpoint
- Resume: `Command(resume=value)` -> continue từ checkpoint
- Approval flow: tool execution cần approve trước khi chạy
- Input collection: ask user for input mid-execution
- HumanInTheLoopMiddleware: `interrupt_on={"tool_name": True}`
- Timeout: auto-resume sau timeout nếu không có phản hồi
- UI notification: gửi interrupt notification tới gateway

### Task 7.4: Task Dispatch & Workflow Engine

**Mô tả:** Xây dựng task dispatch system và workflow engine cho multi-step tasks.

**File tham khảo:**
- chatbot-orchestrator: `task_engine.py` (TaskEngine), `core/registry.py` (HandlerRegistry), `core/handler.py` (BaseHandler)

**Yêu cầu:**
- Task definition: task schema với kind, backend, version
- Task execution: lifecycle management (pending -> processing -> done/error)
- Handler registry: (kind, backend, version) -> handler
- Version-aware dispatch: major match + <= version
- Adapter chain: payload migration between versions
- Workflow orchestration: sequence tasks, parallel tasks, conditional tasks
- Task tree: parent/child task hierarchy
- Input/output binding: variable resolution cho task params
- Error propagation: task error -> parent task -> root task

### Task 7.5: Event System & Error Handling

**Mô tả:** Implement event system và centralized error handling.

**File tham khảo:**
- chatbot-orchestrator: event system (EventToTriggerTask, OrchestratorEvent), `task_engine.py` error handling
- LangGraph: error types, error handler interceptor

**Yêu cầu:**
- Event types: `error_event`, `message_event`, `end_plan_event`, `progress_event`
- Exception-based events: raise EventToTriggerTask -> bắt và xử lý
- Event propagation: child -> parent -> root
- Centralized error handling:
  - Error classification: transient vs permanent
  - Error recovery: retry, fallback, degrade
  - Error notification: gửi event tới gateway
  - Error tracing: event trace stack (plan -> routine -> ...)
- Message broker integration:
  - Kafka publisher: SASL_SSL / SCRAM-SHA-512
  - ActiveMQ publisher: STOMP protocol
  - Factory pattern: `MessageBrokerFactory.get_broker(type, **kwargs)`
- Circuit breaker: cho external service calls
- Rate limiting: prevent event flooding