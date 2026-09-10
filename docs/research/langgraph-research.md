# LangGraph Research

## 1. Tong quan cau truc thu muc

```
langgraph/
|-- libs/
|   |-- langgraph/                  # Core library
|   |   |-- langgraph/
|   |   |   |-- graph/              # Builder API (StateGraph, MessageGraph)
|   |   |   |-- pregel/             # Runtime engine (Pregel algorithm)
|   |   |   |-- channels/           # Channel types (state communication primitives)
|   |   |   |-- managed/            # Managed values (internal state)
|   |   |   |-- func/               # Functional API (entrypoint, task decorators)
|   |   |   |-- _internal/          # Internal utilities (serde, config, queue, etc.)
|   |   |   |-- stream/             # Streaming infrastructure
|   |   |   |-- types.py            # Public types (Command, Send, Interrupt, etc.)
|   |   |   |-- config.py           # Configuration helpers
|   |   |   |-- runtime.py          # Runtime context injection
|   |   |   |-- constants.py        # Constants (START, END, TAG_HIDDEN)
|   |   |   |-- errors.py           # Error types
|   |   |   |-- callbacks.py        # Callback types
|   |   |   |-- typing.py           # Type variables
|   |   |-- tests/                  # Test suite
|   |   |-- bench/                  # Benchmarking
|   |
|   |-- checkpoint/                 # Checkpoint/persistence layer
|   |   |-- langgraph/checkpoint/
|   |   |   |-- base/               # BaseCheckpointSaver, Checkpoint, Metadata types
|   |   |   |-- memory/             # InMemorySaver
|   |   |   |-- serde/              # Serialization (JsonPlus, msgpack, encrypted)
|   |   |-- langgraph/store/        # Key-value store (BaseStore, InMemoryStore)
|   |   |-- langgraph/cache/        # Caching (BaseCache, InMemoryCache)
|   |
|   |-- checkpoint-sqlite/          # SQLite checkpoint implementation
|   |-- checkpoint-postgres/        # Postgres checkpoint implementation
|   |-- prebuilt/                   # Prebuilt agent patterns (ReAct, tool node)
|   |-- cli/                        # CLI tool
|   |-- sdk-py/                     # Python SDK
|   |-- sdk-js/                     # JavaScript SDK
|
|-- examples/                       # Example usage
|-- docs/                           # Documentation generation
```

---

## 2. Cac module/core concepts chinh

### 2.1 Graph (Builder)

**File:** `/libs/langgraph/langgraph/graph/state.py`

- **`StateGraph`**: Builder class, implements the **Builder pattern**. Cho phep nguoi dung xay dung graph bang cach add nodes, edges, conditional edges, sau do `compile()` thanh `CompiledStateGraph`.
- **`CompiledStateGraph`**: Ke thua tu `Pregel`, la compiled graph co the `invoke()`, `stream()`, `ainvoke()`, `astream()`.
- **`MessageGraph`**: Convenience wrapper (deprecated) cho chat-based graphs.
- **`add_messages`**: Reducer function dac biet cho message state, merge messages by ID.

### 2.2 Pregel Engine (Runtime)

**File:** `/libs/langgraph/langgraph/pregel/main.py`

- **`Pregel`**: Core runtime class, implements **Pregel Algorithm** (Bulk Synchronous Parallel model). Day la trung tam cua toan bo thu vien.
- **`NodeBuilder`**: Fluent builder de tao `PregelNode` truc tiep (cho advanced use cases).
- **`PregelNode`**: Dinh nghia mot actor trong graph -- chua channels doc, triggers, writers, bound logic.

**Pregel Algorithm** (3 phases per step):
1. **Plan**: Xac dinh actors nao chay trong step nay (dua tren channel versions va triggers).
2. **Execute**: Chay tat ca actors da chon trong parallel.
3. **Update**: Cap nhat channels voi cac gia tri actors da write.

### 2.3 Channels (State Communication)

**File:** `/libs/langgraph/langgraph/channels/`

- **`BaseChannel`**: Abstract base class cho moi channel type.
- **`LastValue`**: Mac dinh -- chi luu gia tri cuoi cung, nhan toi da 1 update per step.
- **`LastValueAfterFinish`**: Giong LastValue nhung chi available sau khi step ket thuc.
- **`EphemeralValue`**: Chi ton tai trong 1 step, khong duoc persist vao checkpoint.
- **`BinaryOperatorAggregate`**: Dung reducer function de aggregate nhieu updates.
- **`Topic`**: Configurable PubSub -- co the accumulate nhieu values, dedup.
- **`NamedBarrierValue`**: Dung de synchronize -- cho nhieu nodes hoan thanh truoc khi trigger node tiep.
- **`NamedBarrierValueAfterFinish`**: Nhu tren nhung chi trigger sau step ket thuc.
- **`DeltaChannel`**: Chi luu thay doi (delta) thay vi toan bo state, voi snapshot frequency.

### 2.4 Checkpoint & Persistence

**File:** `/libs/checkpoint/langgraph/checkpoint/base/__init__.py`

- **`Checkpoint`**: TypedDict representing state snapshot: `v`, `id`, `ts`, `channel_values`, `channel_versions`, `versions_seen`.
- **`BaseCheckpointSaver`**: Abstract class cho persistence backend. Method chinh: `get`, `get_tuple`, `list`, `put`, `put_writes`.
- **`CheckpointMetadata`**: Metadata di kem (`source`, `step`, `parents`, `run_id`).
- **`PendingWrite`**: Cac writes chua duoc applied, giu cho crash recovery.

**Implementations**: InMemorySaver, SQLiteSaver, PostgresSaver.

### 2.5 Serialization

**File:** `/libs/checkpoint/langgraph/checkpoint/serde/`

- **`SerializerProtocol`**: Interface cho serde.
- **`JsonPlusSerializer`**: JSON-based serializer handle datetime, numpy, pandas.
- **`EncryptedSerializer`**: AES-GCM encrypted serialization.

### 2.6 Store (Long-term Memory)

**File:** `/libs/checkpoint/langgraph/store/base/__init__.py`

- **`BaseStore`**: Key-value store interface, co the support semantic search (`put`, `get`, `search`).
- **`InMemoryStore`**: In-memory implementation.

### 2.7 Managed Values

**File:** `/libs/langgraph/langgraph/managed/base.py`

- **`ManagedValue`**: Abstract class cho managed values (internal state khong phai channel).
- **`ManagedValueMapping`**: Dict cua managed values.

### 2.8 Functional API

**File:** `/libs/langgraph/langgraph/func/__init__.py`

- **`@entrypoint`**: Decorator de dinh nghia workflow bang function API.
- **`@task`**: Decorator de dinh nghia task co the duoc parallel invoke.
- **`SyncAsyncFuture`**: Future object support ca sync va async.

### 2.9 Prebuilt Patterns

**File:** `/libs/prebuilt/langgraph/prebuilt/`

- **`create_react_agent`**: Tao ReAct agent graph.
- **`ToolNode`**: Node de invoke tools.
- **`InjectedState`**, **`InjectedStore`**: Dependency injection mechanisms.

---

## 3. Design Patterns duoc su dung

### 3.1 Builder Pattern
- **`StateGraph`** la builder: `add_node()` -> `add_edge()` -> `add_conditional_edges()` -> `compile()`.
- **`NodeBuilder`** la builder de tao `PregelNode`: `subscribe_to()` -> `do()` -> `write_to()` -> `build()`.

### 3.2 Actor Model
- Moi **`PregelNode`** la mot actor doc channels, xu ly, va write channels.
- Actors giao tiep gian tiep qua channels, khong goi truc tiep nhau.

### 3.3 Bulk Synchronous Parallel (BSP)
- Pregel engine implement BSP: Plan -> Execute (parallel) -> Update.
- Moi superstep la mot BSP iteration.

### 3.4 Publish-Subscribe (PubSub)
- **`Topic`** channel la mot PubSub primitive.
- Nodes subscribe to channels thong qua `triggers`.
- Channel updates publish den tat ca subscriber nodes.

### 3.5 Strategy Pattern
- **Channel types**: Thay doi behavior qua channel type (LastValue vs Topic vs BinaryOperatorAggregate).
- **RetryPolicy, CachePolicy, TimeoutPolicy**: Strategy cho retry, cache, timeout behavior.
- **Serializers**: Strategy cho serialization format (JsonPlus, msgpack, encrypted).

### 3.6 Abstract Factory / Factory Method
- `_get_channel()`, `_is_field_channel()`, `_is_field_binop()`, `_is_field_managed_value()` chuyen doi type annotations thanh channel instances.

### 3.7 Chain of Responsibility
- **Retry policies**: Multiple retry policies co the duoc chain lai, apply first matching.
- **Error handlers**: Node-level error handler chain: specific error handler > default error handler.

### 3.8 Template Method
- **`BaseChannel`**: Dinh nghia template (`get`, `update`, `checkpoint`, `from_checkpoint`), subclass implement cu the.

### 3.9 State Pattern
- **Graph execution state**: `Checkpoint` chua toan bo execution state (channel values, versions, versions_seen).
- **Replay**: Co the replay graph tu bat ky checkpoint nao.

### 3.10 Value Object / Immutable Data
- **`Send`**, **`Interrupt`**, **`Command`**, **`RetryPolicy`**: Immutable / frozen dataclasses.
- **`Checkpoint`**: TypedDict read-only sau khi duoc tao.

### 3.11 Dependency Injection
- Thong qua `Runtime` object cung cap context, store, writer cho nodes.
- `InjectedState`, `InjectedStore`, `InjectedToolArg` cho tool calls.

### 3.12 Interceptor Pattern
- **Node-level error handlers**: Intercept exceptions tu nodes, co the handle va continue execution.

---

## 4. State Management

### 4.1 Channel-based State

State trong LangGraph duoc quan ly hoan toan thong qua **channels**. Moi field trong state schema tro thanh mot channel:

```
State schema (TypedDict)  -->  Channel mapping
{
    "messages": Annotated[list, add_messages]  -->  Topic channel (accumulate)
    "x": int                                    -->  LastValue channel (last value)
    "total": Annotated[int, operator.add]       -->  BinaryOperatorAggregate
}
```

### 4.2 Channel Versions và Trigger Mechanism

- Moi channel co mot **version** (monotonically increasing).
- Moi node track **versions_seen** -- version cua tung channel ma node da doc.
- Khi channel version thay doi, node co trigger match channel do se duoc schedule trong step tiep theo.
- Day la co che routing/flow control chinh cua Pregel.

### 4.3 State Updates via Writers

Cac nodes khong truc tiep modify state ma thong qua **writes**:

1. Node execution sinh ra ket qua (dict, Command, etc.)
2. **`ChannelWrite`** xu ly ket qua, convert thanh `(channel, value)` tuples.
3. **Writers** (ChannelWrite, ChannelWriteEntry, ChannelWriteTupleEntry) ghi writes vao pending writes.
4. Cuoi step, **`apply_writes()`** duoc goi de update channels voi pending writes.
5. Moi channel type xu ly updates rieng:
   - `LastValue`: nhan 1 value, overwrite.
   - `BinaryOperatorAggregate`: apply reducer function len current value.
   - `Topic`: accumulate values, co the dedup.

### 4.4 Checkpointing

Checkpoint la snapshot cua toan bo state tai mot thoi diem:

```python
@dataclass
class Checkpoint:
    v: int                    # Version
    id: str                   # Unique ID (monotonically increasing)
    ts: str                   # ISO 8601 timestamp
    channel_values: dict      # Snapshot values
    channel_versions: dict    # Version counter per channel
    versions_seen: dict       # Per-node version tracking
```

- Checkpoint duoc tao moi step (neu checkpointer enabled).
- **Pending writes** duoc luu rieng trong `checkpoint_writes` table de crash recovery.
- Co the "time travel" -- replay state history bang cach query old checkpoints.
- `update_state()` cho phep manually modify state bang cach fake writes tu mot node.

### 4.5 Delta Channels (Optimization)

Delta channels chi luu thay doi thay vi toan bo state, giam checkpoint size trade-off voi higher read complexity.

### 4.6 State Reducers

Reducers duoc dinh nghia qua Python's `Annotated` type hint:

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]  # Reducer = add_messages
    total: Annotated[int, operator.add]      # Reducer = operator.add
```

Reducers duoc convert thanh `BinaryOperatorAggregate` channels tai compile time.

---

## 5. Routing / Flow Control

### 5.1 Edge-based Routing

**Simple edge** (`add_edge`):
```
Node A -> Node B
```
- Node A write to "branch:to:B" channel.
- Node B subscribe to "branch:to:B" channel.
- Khi channel duoc write, Node B duoc trigger.

**Multiple parent edges** (`add_edge([A, B], C)`):
- Tao `NamedBarrierValue` channel.
- Ca A va B phai hoan thanh truoc khi C duoc trigger.

### 5.2 Conditional Routing

**Conditional edge** (`add_conditional_edges`):
```python
graph.add_conditional_edges("A", router_function, {"dest1": "B", "dest2": "C"})
```
- **`BranchSpec`** chua path function va path_map.
- `_route()` invoke path function, nhan ket qua, map to node name.
- Tao `ChannelWriteEntry(branch:to:X)` de trigger node dich.

### 5.3 Dynamic Routing via Send

- Node co the return `Send("node_name", state)` de dynamically trigger mot node voi custom state.
- `Send` objects duoc luu trong `TASKS` channel (Topic).
- `prepare_next_tasks()` doc tu TASKS channel de schedule push-style tasks.
- Cho phep **map-reduce patterns**: 1 node fan out to multiple parallel nodes.

### 5.4 Command-based Routing

- Node co the return `Command(goto="node_name")` hoac `Command(goto=Send(...))`.
- `_control_branch()` xu ly Command, convert `goto` thanh channel writes.
- `Command(graph=Command.PARENT)` cho phep subgraph gui command len parent graph.

### 5.5 Interrupt and Resume

- **`interrupt(value)`**: Tam dung graph execution, nem `GraphInterrupt` exception.
- State duoc checkpointed truoc interrupt.
- Resume bang `Command(resume=value)` de continue tu diem interrupted.
- Dua tren co che pending writes dac biet (`__interrupt__`, `__resume__` channels).

### 5.6 Subgraph Routing

- **Subgraphs** co namespace rieng (vd: `node_name:task_id|subnode:task_id`).
- Checkpoint namespace separation dam bao isolation.
- `Command(graph=Command.PARENT)` cho phep subgraph dieu huong parent.

### 5.7 Start/End Flow

- **START**: Virtual node, trigger graph execution.
- **END**: Virtual node, dung execution khi graph reaches END.
- `set_entry_point()` -> `add_edge(START, node)`.
- `set_finish_point()` -> `add_edge(node, END)`.

### 5.8 Graph Compilation

Khi `compile()` duoc goi:

1. **Validate**: Kiem tra node names, edge consistency, interrupt targets.
2. **Map channels**: Convert state schema keys thanh `BaseChannel` instances.
3. **Attach nodes**: Moi `StateNode` -> `PregelNode` voi triggers, readers, writers.
4. **Attach edges**: Moi `add_edge` -> ChannelWrite entries trong node's writers.
5. **Attach branches**: Moi `add_conditional_edges` -> BranchSpec -> BranchSpec.route() van ga vao writers.
6. **Return `CompiledStateGraph`** ke thua `Pregel`.

---

## 6. Interfaces / Abstractions Important

### 6.1 Core Interfaces

| Interface | File | Role |
|-----------|------|------|
| `BaseChannel[V, U, C]` | `channels/base.py` | Channel abstraction: `get()`, `update()`, `checkpoint()`, `from_checkpoint()` |
| `PregelProtocol` | `pregel/protocol.py` | Protocol cho graph execution: `invoke`, `stream`, `get_state`, etc. |
| `BaseCheckpointSaver[V]` | `checkpoint/base/__init__.py` | Persistence interface: `put`, `get`, `list`, `put_writes` |
| `BaseStore` | `store/base/__init__.py` | Long-term memory store: `put`, `get`, `search`, `delete` |
| `BaseCache` | `cache/base/__init__.py` | Cache interface: `lookup`, `update`, `clear` |
| `SerializerProtocol` | `checkpoint/serde/base.py` | Serialization: `dumps`, `loads`, `dumps_typed`, `loads_typed` |
| `ManagedValue` | `managed/base.py` | Managed value: `get(scratchpad)` |
| `Runnable` (langchain_core) | External | Base interface cho moi component co the invoke |
| `RunnableConfig` (langchain_core) | External | Configuration propagation khap graph |

### 6.2 Key Data Types

| Type | File | Role |
|------|------|------|
| `Checkpoint` | `checkpoint/base/__init__.py` | State snapshot |
| `CheckpointTuple` | `checkpoint/base/__init__.py` | Checkpoint + metadata + pending writes |
| `CheckpointMetadata` | `checkpoint/base/__init__.py` | Metadata (source, step, parents) |
| `Send` | `types.py` | Dynamic message to node |
| `Command[N]` | `types.py` | Graph control: update, goto, resume |
| `Interrupt` | `types.py` | Interrupt info |
| `PregelTask` | `types.py` | Task definition |
| `PregelExecutableTask` | `types.py` | Executable task with proc, config, retry |
| `StateSnapshot` | `types.py` | State query result |
| `RetryPolicy` | `types.py` | Retry configuration |
| `TimeoutPolicy` | `types.py` | Timeout configuration |
| `CachePolicy` | `types.py` | Cache configuration |
| `TracePolicy` | `types.py` | Trace configuration |
| `StreamMode` | `types.py` | Stream mode constant |
| `PregelNode` | `pregel/_read.py` | Node definition (channels, triggers, writers, bound) |
| `PregelTaskWrites` | `pregel/_algo.py` | Task writes for checkpoint |
| `ChannelWriteEntry` | `pregel/_write.py` | Single channel write entry |
| `BranchSpec` | `graph/_branch.py` | Conditional branch specification |
| `StateNodeSpec` | `graph/_node.py` | Node spec in StateGraph |

### 6.3 Key Abstraction Hierarchies

**Channel Hierarchy:**
```
BaseChannel[V, U, C]
|-- LastValue[V]          (default, stores last value)
|-- LastValueAfterFinish   (available only after step ends)
|-- EphemeralValue[V]     (1-step only, not persisted)
|-- BinaryOperatorAggregate[V, U] (reducer-based)
|-- Topic                 (PubSub, accumulate, dedup)
|-- NamedBarrierValue     (synchronization barrier)
|-- DeltaChannel          (delta-only persistence)
```

**Graph Hierarchy:**
```
Runnable (langchain_core)
|-- PregelProtocol
    |-- Pregel (generic)
        |-- CompiledStateGraph (StateGraph compiled)
```

**Serialization Hierarchy:**
```
SerializerProtocol
|-- JsonPlusSerializer    (JSON + extensions)
|-- MsgpackSerializer     (msgpack)
|-- EncryptedSerializer   (AES-GCM encrypted)
```

---

## 7. Key Insights

1. **LangGraph la mot distributed computing framework cho AI agents**: Kien truc dua tren Pregel Algorithm (Google Pregel), khong phai DAG/Graph-based engine thong thuong. Cho phep cycles va complex flow.

2. **Separation of Builder vs Runtime**: `StateGraph` la builder tao graph definition; `Pregel` la runtime engine thuc thi. Compilation la qua trinh chuyen doi builder representation thanh runtime representation.

3. **Channel abstraction la trung tam**: Moi state field -> channel. Channel versions + trigger mechanism la co che flow control chinh, khong phai explicit routing table.

4. **Checkpoints la trung tam cho persistence va recovery**: Checkpoints cho phep pause/resume, time travel, human-in-the-loop, fork.

5. **Actor Model**: Nodes doc state, xu ly, va write state updates channels. Khong co direct communication giua cac nodes.

6. **Extensibility qua Channel types va Reducers**: Them channel type cho custom behavior; reducers aggregate state updates.

7. **Sync/Async consistency**: Toan bo core design support ca sync va async execution thong qua pairs of methods (invoke/ainvoke, stream/astream, etc.).