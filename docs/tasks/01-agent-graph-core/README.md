# Agent Graph Core

> **Nguồn tham khảo:** LangGraph `pregel/main.py` (Pregel engine), `graph/state.py` (StateGraph builder), DeepAgents `graph.py` (create_deep_agent), chatbot-orchestrator `components/agent/deepagent/graph.py`

## Mục tiêu

Xây dựng core graph engine cho agent dựa trên LangGraph Pregel Algorithm. Đây là nền tảng cho toàn bộ agent system, bao gồm state management, node execution, và graph compilation.

## Tasks

### Task 1.1: StateGraph Builder với Custom State Schema

**Mô tả:** Xây dựng StateGraph với custom state schema kế thừa từ `AgentState`. State schema định nghĩa tất cả các field mà agent graph sử dụng: messages, tool calls, memory, metadata.

**File tham khảo:**
- LangGraph: `/libs/langgraph/langgraph/graph/state.py` (StateGraph, CompiledStateGraph)
- DeepAgents: `deepagents/graph.py` (DeepAgentState)
- chatbot-orchestrator: `components/agent/deepagent/graph.py`

**Yêu cầu:**
- Tạo `AgentState` schema với `Annotated[messages, add_messages]` cho conversation
- Thêm các field phụ: `metadata`, `context`, `current_step`
- Hỗ trợ TypedDict + dataclass cho context schema
- Implement `compile()` method -> `CompiledStateGraph`

### Task 1.2: Node Definition System

**Mô tả:** Xây dựng hệ thống định nghĩa node cho agent graph. Mỗi node đại diện cho một bước trong agent execution.

**File tham khảo:**
- LangGraph: `pregel/_read.py` (PregelNode), `graph/_node.py` (StateNodeSpec)
- DeepAgents: `middleware/__init__.py`

**Yêu cầu:**
- Tạo `AgentNode` base class với lifecycle hooks (before_node, execute, after_node)
- Hỗ trợ function-based nodes (decorator `@node`)
- Hỗ trợ class-based nodes với state injection
- Channel subscription và trigger mechanism

### Task 1.3: Channel-based State Management

**Mô tả:** Implement channel-based state management như LangGraph's channel system. Mỗi state field là một channel với behavior riêng.

**File tham khảo:**
- LangGraph: `channels/base.py` (BaseChannel), `channels/last_value.py`, `channels/topic.py`, `channels/binop.py`

**Yêu cầu:**
- Implement các channel types: LastValue, BinaryOperatorAggregate, Topic, EphemeralValue
- Channel version tracking cho trigger mechanism
- Pending writes support cho crash recovery
- Delta channel optimization cho messages

### Task 1.4: Graph Compilation Pipeline

**Mô tả:** Xây dựng compilation pipeline: từ StateGraph builder representation sang runtime Pregel representation.

**File tham khảo:**
- LangGraph: `graph/state.py` compile(), `pregel/main.py` Pregel

**Yêu cầu:**
- Validate graph: cycles, unreachable nodes, type consistency
- Map state schema keys -> BaseChannel instances
- Attach nodes: StateNode -> PregelNode với triggers, readers, writers
- Attach edges: ChannelWrite entries trong node's writers
- Attach branches: BranchSpec -> routing logic
- Return CompiledStateGraph

### Task 1.5: Invoke / Stream Execution Loop

**Mô tả:** Implement execution loop cho agent graph: invoke, stream, astream.

**File tham khảo:**
- LangGraph: `pregel/main.py` (Pregel.invoke, Pregel.stream), `pregel/_algo.py`
- DeepAgents: `graph.py` (create_deep_agent assembly)

**Yêu cầu:**
- Implement Pregel Algorithm loop: Plan -> Execute (parallel) -> Update
- Superstep mechanism: mỗi step là một BSP iteration
- Stream modes: "messages", "updates", "events"
- Human-in-the-loop interrupt/resume
- Replay từ checkpoint

### Task 1.6: Error Handling & Retry

**Mô tả:** Xây dựng error handling và retry mechanism cho node execution.

**File tham khảo:**
- LangGraph: `pregel/_retry.py`, `types.py` (RetryPolicy)
- chatbot-orchestrator: `components/agent/deepagent/middleware/model_retry.py`, `tool_retry.py`

**Yêu cầu:**
- Node-level error handlers (interceptor pattern)
- RetryPolicy: max_attempts, backoff, retry_on
- TimeoutPolicy: per-node timeout
- Error propagation: từ subgraph lên parent graph
- Graceful degradation khi node fail

### Task 1.7: Graph Visualization & Debug

**Mô tả:** Implement visualization và debug tools cho agent graph.

**File tham khảo:**
- LangGraph: `pregel/debug.py`, `pregel/_draw.py`

**Yêu cầu:**
- Graph visualization (Mermaid/Mermaid.js generation)
- Debug mode: step-by-step execution trace
- State inspector: xem channel values tại mọi checkpoint
- Stream debug: collector + printer (như chatbot-orchestrator's StreamCollector)

### Task 1.8: Subgraph Support

**Mô tả:** Implement subgraph support: agent graph có thể chứa subgraphs.

**File tham khảo:**
- LangGraph: `pregel/main.py` subgraph handling, `graph/state.py` add_node with subgraph

**Yêu cầu:**
- Subgraph namespace isolation (checkpoint separation)
- Parent-child communication: Command(graph=Command.PARENT)
- Subgraph context isolation: state không merge vào parent
- Recursion limit per subgraph

### Task 1.9: DeepAgents Integration Layer

**Mô tả:** Xây dựng integration layer giữa graph core và DeepAgents features (skills, memory, profiles).

**File tham khảo:**
- DeepAgents: `graph.py` (create_deep_agent assembly)
- chatbot-orchestrator: `components/agent/deepagent/graph.py` (create_deep_agent_v12)

**Yêu cầu:**
- DeepAgents middleware stack integration
- HarnessProfile resolution
- ProviderProfile integration
- Skills middleware integration
- Memory middleware integration
- System prompt assembly (prefix + base + suffix + profile)