# Phan Tich Kien Truc Agent System - orchestrator

**Nguon:** `/home/trongnd/Documents/orchestrator/agent-system-report.md`
**Phan tich boi:** Vertex Agent Research
**Ngay:** 2026-09-09

---

## 1. Kien Truc Tong The

He thong la mot **task-driven orchestration engine** — moi hanh vi chatbot duoc dinh nghia duoi dang cac **task** co kieu (kind). Agent System dong vai tro la mot **plugin** trong he sinh thai do.

### Stack Cong Nghe

| Layer         | Cong Nghe                                     |
| ------------- | --------------------------------------------- |
| API Server    | FastAPI, Port 8345                            |
| Orchestration | TaskEngine (~2200 dong), Python ThreadPool    |
| AI Framework  | LangGraph, LangChain, DeepAgents              |
| LLM Access    | OpenAI SDK, LiteLLM Proxy, MCP Proxy          |
| State Machine | LangGraph StateGraph (CompiledStateGraph)     |
| Checkpointing | MongoDB (MongoDBSaver)                        |
| Store         | MongoDB (MongoDBStore)                        |
| Streaming     | Producer -> Formatter -> Transport -> Gateway |
| Session State | Redis / HTTP / In-Memory                      |
| Observability | Langfuse                                      |

### Mo hinh 4-Tier

| Tier                     | Thanh phan                         | Vai tro                                                                    |
| ------------------------ | ---------------------------------- | -------------------------------------------------------------------------- |
| Tier 1: API Layer        | `orchestrator.py`                  | FastAPI HTTP Server, nhan request va phan phoi                             |
| Tier 2: Task Engine      | `task_engine.py`                   | Trung tam orchestration, quan ly TaskExecution lifecycle                   |
| Tier 3: Handler Registry | `core/registry.py` + `components/` | Version-aware dispatch, adapter chain                                      |
| Tier 4: Agent Runtimes   | 6+ handler implementations         | Thuc thi agent logic (OpenAI loop, DeepAgent v1/v2/v3, AgentExecutor, AIQ) |

---

## 2. Cac Thanh Phan Chinh

### 2.1 Orchestrator (`orchestrator.py`)

- FastAPI server lang nghe port 8345
- Cac endpoint: `POST /start`, `POST /start_task`, `GET /get_execution`
- Su dung ThreadPoolExecutor de chay task trong tien trinh rieng (`run_task_in_process()`)

### 2.2 Task Engine (`task_engine.py`)

- ~2200 dong code — trai tim cua he thong
- Nhan `TaskExecution` va `task_id`, load task definition tu DB, dispatch toi handler
- Quan ly: execution lifecycle, variables, errors, events
- Flow chinh: `start_task()` -> `dispatch_task()` -> `registry.dispatch()`

### 2.3 Handler Registry (`core/registry.py`)

- **3 chieu:** kind x backend x version
- Tu dong discover handler qua `autodiscover()` (walk `components/` package)
- Ho tro **AdapterChain** de migrate payload format giua cac version
- Giai thuat dispatch: tim bucket -> upcast payload (neu co adapter) -> resolve factory -> handler.handle()

### 2.4 Agent Runtimes

Co **6 agent runtime** khac nhau:

| Runtime             | Kind          | Backend   | Version | Dac diem chinh                                                     |
| ------------------- | ------------- | --------- | ------- | ------------------------------------------------------------------ |
| Agent (OpenAI Loop) | Agent         | DEFAULT   | v1.0.0  | Vong lap LLM don gian, khong streaming, khong middleware           |
| AgentExecutor       | AgentExecutor | DEFAULT   | -       | Thuc thi song song tool calls (ThreadPool, max 3 workers)          |
| DeepAgent v1        | DeepAgent     | DEFAULT   | v1.0.0  | Base version, it middleware                                        |
| DeepAgent v2        | Agent         | DeepAgent | v1.2.0  | Enhanced: 7 middleware modules, Sandbox, Skills, Memory, Subagents |
| DeepAgent v3        | Agent         | DeepAgent | v3.0.0  | Day du nhat: 15 middleware modules, Async subagents                |
| AIQ Agent           | DeepAgent     | -         | -       | Deep Researcher                                                    |

### 2.5 Streaming Pipeline

Kien truc 4 thanh phan:

```
Producer -> Transport -> Formatter -> Gateway
```

- **Producers:** LangGraphProducer, OpenAIProducer, Simulator
- **Formatters:** ChatboxFormatter (NDJSON), OpenAIFormatter (SSE), ClaudeFormatter (block-based)
- **Transport:** StreamTransport voi retry policy, CancelToken, replay buffer
- **Gateway:** POST /api/receive-stream-v2 -> real-time UI

### 2.6 Middleware Stack (DeepAgent v3)

15 middleware modules theo thu tu:

1. FirstMiddleware - Gui thong diep khoi tao
2. ToolingMiddleware - Quan ly tool registry
3. TodoListMiddleware - Tool quan ly todo list
4. AgentCurrentStateMiddleware - Theo doi state agent
5. SkillsMiddleware - Load skills tu backend
6. Middleware_3 - Custom xu ly tool calls
7. FilesystemMiddleware - File operations
8. SubAgentMiddleware - Subagent spawning
9. SummarizationMiddleware - Auto-summarize context
10. PatchToolCallsMiddleware - Patch tool call arguments
11. AnthropicPromptCachingMiddleware - Prompt caching
12. MemoryMiddleware - Memory injection
13. HumanInTheLoopMiddleware - Interrupt khi can phe duyet
14. Headless Tools Middleware - UI interaction tools
15. LastMiddleware - Finalize stream

### 2.7 Tool Categories

| Loai              | Type Field         | Co che                           |
| ----------------- | ------------------ | -------------------------------- |
| Task Tool         | "tool"             | Goi task definition tu DB        |
| Plan Tool         | "plan"             | Goi plan tu bot khac             |
| MCP Tool          | "mcpserver"        | Goi MCP server qua LiteLLM proxy |
| Code Interpreter  | "code_interpreter" | Python sandbox                   |
| RAGFlow Knowledge | "ragflow_tool"     | Retrieval tu knowledge base      |

### 2.8 State Management

- **Variable scopes:** plan (trong execution), bot (cross-session), sys (global)
- **Session state implementations:** InMemory (test), Redis (production), HTTP (remote)
- **Chat history:** Luu trong `plan.plan_history`, ho tro allMessages va windowSize
- **Memory files (DeepAgent v2):** USER.md, MEMORY.md, IDENTITY.md, AGENTS.md

### 2.9 Event & Error Handling

- **EventToTriggerTask:** ke thua tu `OrchestratorEvent(Exception)`
- Event duoc raise nhu **exception** trong task execution
- Ho tro publish events qua message broker: Kafka (SASL_SSL), ActiveMQ (STOMP)
- Factory pattern: `MessageBrokerFactory.get_broker(type, **kwargs)`
- Event types: error_event, message_event, end_plan_event

---

## 3. Design Patterns & Workflow Patterns

### 3.1 Design Patterns

| Pattern                                | Ap dung                                                           | Vi tri                          |
| -------------------------------------- | ----------------------------------------------------------------- | ------------------------------- |
| **Pipeline / Chain of Responsibility** | Middleware stack xu ly agent request theo chain                   | Middleware modules              |
| **Strategy Pattern**                   | Nhieu Agent Runtime khac nhau cho cung task type                  | Registry dispatch               |
| **Factory Pattern**                    | Tao formatter, handler, message broker                            | formatters/factory.py, registry |
| **Adapter Pattern**                    | Version migration payload                                         | AdapterChain                    |
| **Observer Pattern**                   | Streaming pipeline: Producer -> Transport -> Formatter -> Gateway | Streaming layer                 |
| **Registry Pattern**                   | HandlerRegistry, version-aware dispatch                           | core/registry.py                |
| **Command Pattern**                    | Task Execution nhu command                                        | task_engine.py                  |
| **Template Method**                    | BaseHandler dinh nghia handle() template                          | core/handler.py                 |
| **Thread Pool**                        | Parallel tool execution                                           | AgentExecutor                   |
| **Data Flow / Pipeline**               | Streaming chunks qua formatters                                   | Streaming pipeline              |

### 3.2 Workflow Patterns

| Pattern                     | Mo ta                                                              |
| --------------------------- | ------------------------------------------------------------------ |
| **Task-Driven Dispatch**    | Moi hanh vi la mot task -> dispatch toi handler phu hop            |
| **Version Migration Flow**  | Payload duoc upcast qua AdapterChain truoc khi xu ly               |
| **Streaming Pipeline Flow** | Raw LLM chunks -> StreamChunk -> Formatter -> bytes -> Gateway     |
| **Parallel Execution**      | AgentExecutor thuc thi tool calls song song (max 3 workers)        |
| **Subagent Spawning**       | Agent tao subagent de xu ly task con                               |
| **Error-as-Event**          | Exception duoc convert thanh EventToTriggerTask de xu ly tap trung |
| **Autodiscovery**           | Tu dong phat hien handler khi khoi dong                            |
| **Checkpoint/Resume**       | MongoDB checkpointer cho phep resume agent state                   |

---

## 4. Communication Giua Cac Agents

### 4.1 Co che Communication

1. **Tool Calls (synchronous):**
   - Agent LLM -> tool_call -> SubAgentMiddleware -> SubAgent chay voi config rieng
   - Agent LLM -> tool_call -> FilesystemMiddleware -> File operation

2. **Subagent (synchronous):**
   - `SubAgent` — declarative, co name/description/system_prompt/model/tools/middleware
   - `CompiledSubAgent` — pre-compiled runnable (chi co runnable)

3. **Async Subagent (asynchronous):**
   - `AsyncSubAgent` — background, co `graph_id` (LangSmith deployment)
   - Quan ly qua AsyncSubAgentMiddleware: launch, check, update, cancel, list

4. **AgentExecutor (parallel):**
   - Nhan list tool calls -> ThreadPool (max 3 workers) -> collect results
   - Dispatch routine task, retrieval task, code interpreter

5. **MCP Protocol:**
   - Agent -> `tool_call(mcp__server__{name}-{tool})`
   - -> `litellm_proxy_get_mcp_tool_meta()` -> `litellm_proxy_call_mcp(args)`
   - Ket qua tra ve content blocks voi structuredContent

6. **Event System:**
   - Exception-based: raise EventToTriggerTask -> TaskEngine bat -> handle
   - Message Broker: Kafka / ActiveMQ cho cross-service communication

### 4.2 Data Flow Patterns

```
User -> API -> TaskEngine -> Registry -> Handler -> Agent Runtime
                                                      |
                                              [LLM <-> Tool Chain]
                                                      |
                                              Streaming Pipeline
                                                      |
                                              Gateway -> UI
```

---

## 5. Scalability & Reliability

### 5.1 Scalability

| Aspect                 | Implementation                                         |
| ---------------------- | ------------------------------------------------------ |
| **Parallel Execution** | ThreadPoolExecutor (max 3 workers) cho tool calls      |
| **Async Subagents**    | Subagents chay trong LangGraph deployment rieng        |
| **Session State**      | Redis backend cho phan tan nhieu instance              |
| **Streaming**          | Bat dong bo, khong block thread                        |
| **Handler Registry**   | Version-aware, de dang them handler moi                |
| **Autodiscovery**      | Tu dong phat hien component, khong can config thu cong |

### 5.2 Reliability

| Aspect               | Implementation                                                        |
| -------------------- | --------------------------------------------------------------------- |
| **Checkpointing**    | MongoDB checkpointer: resume agent state khi fail                     |
| **Retry Policy**     | Transport: max_attempts, backoff, retry_statuses (429, 502, 503, 504) |
| **Replay Buffer**    | 2MB replay buffer cho midstream failure recovery                      |
| **CancelToken**      | Huy streaming khi can                                                 |
| **Error as Event**   | Exception duoc convert thanh event, xu ly tap trung                   |
| **Model Fallback**   | Middleware model_fallback.py                                          |
| **Tool Retry**       | Middleware tool_retry.py                                              |
| **Model Call Limit** | Middleware model_call_limit.py                                        |
| **Adapters**         | Version migration khong breaking change                               |

### 5.3 Observability

| Tool                | Purpose                           |
| ------------------- | --------------------------------- |
| **Langfuse**        | Trace LLM calls                   |
| **LangGraph Debug** | StreamCollector, FileDebugPrinter |
| **MongoDB**         | Checkpointing & Store             |

---

## 6. Bai Hoc Kinh Nghiem & Recommendations

### 6.1 Bai Hoc Kinh Nghiem

1. **Version-Aware Dispatch:** He thong handler registry version-aware (3 chieu: kind x backend x version) la mot thiet ke manh me cho phep:
   - Nhieu handler song song cho cung task type
   - Upgrade dan dan khong breaking change
   - AdapterChain cho migration payload

2. **Task-Driven Architecture:** Moi hanh vi la task -> de mo rong, de test, de debug

3. **Streaming Pipeline Modular:** Producer -> Formatter -> Transport -> Gateway cho phep:
   - De dang them format moi (Chatbox, OpenAI, Claude)
   - Retry logic doc lap voi format
   - Debug de dang (StreamCollector, FileDebugPrinter)

4. **Middleware Stack Pattern:** Chain-of-responsibility cho Agent runtime la pattern linh hoat:
   - Them bot middleware ma khong can sua agent core
   - De dang enable/disable middleware (Skills bi disable o v3)
   - Reuse middleware giua cac version

5. **Error-as-Event:** Xu ly loi bang exception-based event system giup:
   - Xu ly loi tap trung
   - Trace day du (plan -> routine -> ...)
   - De dang tich hop message broker

### 6.2 Recommendations

1. **Consolidate Runtimes:** Co qua nhieu agent runtime (6+). Can consolidate xung quanh DeepAgent v3, loai bo cac runtime cu hon khi co the.

2. **Unify Configuration:** Config giua cac runtime phan tan (advances, task config, tool config). Nen co unified configuration schema.

3. **Improve Testing:**
   - Can unit test cho middleware stack (hien tai la integration tests)
   - Can mock cho LLM calls de test tool calling flow
   - Test coverage cho adapter chain migration

4. **Monitoring & Alerting:**
   - Hien tai chi co Langfuse cho LLM tracing
   - Thieu: metric cho streaming latency, tool execution time, error rate
   - Thieu: health check endpoints

5. **Documentation:**
   - Tai lieu rat chi tiet cho agent system
   - Can bo sung: deployment guide, scaling guide, troubleshooting guide

6. **Security:**
   - Sandbox cho code interpreter (da co)
   - PII redaction middleware (da co)
   - Can: rate limiting middleware, input validation middleware
   - Can: audit logging cho tool execution

7. **Performance:**
   - ThreadPoolExecutor voi max 3 workers co the la bottleneck
   - Can xem xet async execution thay vi thread pool
   - Streaming pipeline co them latency: can benchmark end-to-end

8. **Error Handling:**
   - Exception-based event system hieu qua nhung can canh bao ve exception flooding
   - Can theem circuit breaker pattern cho external service calls

9. **State Management:**
   - 3 session state backends (InMem, Redis, HTTP) la tot
   - Can consistent hashing cho Redis khi scale ngang
   - Consider: distributed cache for tool results

10. **Versioning Strategy:**
    - Hien tai: major match + <= version
    - Can consider: semantic versioning cho handlers, deprecation policy
    - Can health check cho adapter chain migration

---

## 7. File Structure Overview

```
orchestrator/
├── orchestrator.py              # FastAPI server
├── task_engine.py               # Core engine (~2200 dong)
├── models.py                    # 22 task types
├── core/
│   ├── registry.py              # HandlerRegistry, autodiscover
│   ├── handler.py               # BaseHandler
│   ├── adapter.py               # AdapterChain
│   └── interface/               # Interfaces
├── streaming/                   # Streaming pipeline
│   ├── producers/               # LangGraph, OpenAI, Simulator
│   ├── formatters/              # Chatbox, OpenAI, Claude
│   └── transport.py             # StreamTransport
├── components/                  # All handlers
│   ├── agent/                   # Agent + DeepAgent
│   │   └── deepagent/
│   │       ├── graph.py         # LangGraph assembly
│   │       ├── helpers.py
│   │       ├── handlers/        # v2, v3 handlers
│   │       └── middleware/      # 15+ middleware modules
│   ├── agent_executor/          # Parallel tool execution
│   ├── deepagent/               # DeepAgent DEFAULT
│   ├── routine/                 # Routine handler
│   ├── plan/                    # Plan handler
│   ├── send_message/            # SendMessage handler
│   └── ... (15+ component directories)
├── session_state_*.py           # Session backends
├── utils.py                     # Utilities
└── tests/                       # Tests
```

---

## 8. Key Insights

1. **He thong duoc thiet ke voi tinh modular cao**, cho phep plug-and-play cac agent runtime khac nhau ma khong can sua doi core engine.

2. **Version-aware registry la diem manh nhat:** 3 chieu (kind x backend x version) + AdapterChain cho phep he thong phat trien ma khong pha vo backward compatibility.

3. **Middleware stack pattern (15 modules)** cho phep agent runtime co the mo rong linh hoat. Tuy nhien, v3 da disable mot so middleware (Skills, Memory, Deep Research), cho thay qua trinh refactoring dang dien ra.

4. **Streaming pipeline** duoc thiet tot voi modular components, nhung retry policy hien tai `max_attempts=1` (khong retry) co the gay mat data trong production.

5. **He thong hien co 6+ agent runtime** — can consolidate. DeepAgent v3 la runtime tien tien nhat va nen la target cho future development.

6. **Event system thiet ke thong minh** (exception-based + message broker support), nhung can them circuit breaker va rate limiting de tranh cascade failures.

7. **Thieu metric monitoring** cho streaming performance, tool execution time, va error rate — can cai thien production observability.

8. **Kien truc phu hop cho multi-tenant chatbot platform** voi bot-level configuration, session management, va plugin-based component architecture.

---

_Tai lieu tham khao:_ `/home/trongnd/Documents/orchestrator/agent-system-report.md`
