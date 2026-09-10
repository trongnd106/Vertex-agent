# Cross-Repository Feature Analysis & Integration Assessment

Systematic methodology for analyzing a feature in one codebase and evaluating its portability to another.

## When to Use

- Developer asks: "can we port feature X from system A to system B?"
- Need to understand a feature's complete implementation surface (spec + all files)
- Producing a structured integration feasibility report for decision-making

## Workflow

### Phase 1: Spec Understanding

1. **Read the primary specification document** (DOCX, markdown, Google Doc, RFC)
   - Identify the architectural components described
   - Note: triggers, core logic, supporting mechanisms, config hooks
   - For LLM-agent features specifically: identify the agent-loop hooks, fork/spawn mechanisms, tool whitelist patterns

2. **Verify with source code** — the spec may be aspirational or outdated. Cross-reference with the actual codebase.

### Phase 2: Codebase Discovery — Target System (the feature source)

1. **File tree scan** — understand the project layout
2. **Search for key terms** from the spec (function names, class names, config keys)
3. **Follow the dependency chain:**
   - Configuration / init → where triggers are registered
   - Trigger → the handler/spawn function
   - Handler → the core logic
   - Core logic → tools it calls
   - Tests → how it's validated
4. **Read the critical implementation files** — not every file, just the load-bearing ones:
   - Init/config setup (where defaults and intervals live)
   - Orchestrator/loop (where triggers fire)
   - Core logic (the actual work)
   - Supporting utilities (whitelists, summarization, etc.)

### Phase 3: Target Codebase Assessment (where feature would be ported)

1. **File tree scan** of the target system
2. **Identify analogous patterns:**
   - Does the target have a middleware/pipeline architecture?
   - Does it have a tool system? Toolsets?
   - Does it have a fork-agent mechanism? Subprocess spawning? LangGraph sub-graph?
   - Does it have a skill/memory storage layer?
3. **Map each source component to a target equivalent** using a table:
   | Source Component | Target Equivalent | Feasibility | Notes |

### Phase 4: Assessment Output

Structure the final report with:

1. **Feature overview** (2-3 sentence summary from spec)
2. **Complete file inventory** organized by role (Core, Config, Tests, etc.)
3. **Feasibility table** — one row per sub-component, with feasibility rating (High/Medium/Low/Not applicable)
4. **Key blockers** — components that are hard to port (describe why)
5. **Proposed integration roadmap** (phased approach with estimated effort)

## Pitfalls

1. **Reading only the spec, not the code** — specs describe intent, code describes reality. Always verify against actual source.
2. **Threating all files as equally important** — focus on the load-bearing 20% (init, loop, core logic). Helper utilities and tests are supporting evidence, not primary sources.
3. **Missing the dependency chain** — don't jump to a random file; start from the trigger point and follow the call chain forward.
4. **Assuming analogous patterns exist** — just because source system has "forks" doesn't mean target system can fork. Check the target's architecture constraints first.
5. **Overestimating feasibility of prompt caching inheritance** — this is one of the hardest patterns to port between LLM agent frameworks. Note it explicitly as a potential blocker.
6. **Forgetting toolkit/package differences** — target system may use different framework primitives (LangGraph vs raw OpenAI SDK, etc.) that change the integration approach fundamentally.
7. **Assuming middleware/agent-hook semantics match by name.** `AgentMiddleware` in LangChain has a different hook surface than Hermes Agent — `wrap_model_call` wraps the model call, `wrap_tool_call` wraps tool execution, `before_agent`/`after_agent` fire once per conversation lifecycle, `before_model`/`after_model` fire every LLM turn. Don't map by function-name similarity alone; read each hook's actual signature and timing semantics from source code before asserting compatibility.
8. **Missing the middleware chain composition order.** The order middleware is composed determines how it wraps — inner middleware see the LLM response first, outer middleware see the user request first. Understand the assembly order (base → user → tail) before recommending where to insert new middleware.

## Agent/Hook Architecture — Pattern Reference

When the target system uses LangChain AgentMiddleware (as DeepAgent does), understand the hooks by inspecting the source interface directly:

```
Hook               | Fires          | Signature                        | Typical Use
───────────────────|────────────────|──────────────────────────────────|─────────────────────
before_agent       | Once, before   | before_agent(state, runtime)     | Init counters, config
                   | agent loop     |                                  |
after_agent        | Once, after    | after_agent(state, runtime)      | Log totals, cleanup
                   | agent loop     |                                  |
before_model       | Every LLM turn | before_model(state, runtime)     | Count turns, check thresholds
after_model        | Every LLM turn | after_model(state, runtime)      | Analyze response, save state
wrap_model_call    | Wraps LLM call | wrap_model_call(req, handler)    | Inject system prompt, filter tools
wrap_tool_call     | Wraps tool exe | wrap_tool_call(req, handler)     | Count tools calls, restrict tools, log results
```

Key objects passed to hooks:

- **`ModelRequest`**: `.model` (BaseChatModel), `.messages` (list[AnyMessage], no system), `.system_message` (SystemMessage|None), `.tools` (list[BaseTool|dict]), `.state` (AgentState TypedDict, mutable cross-turn), `.runtime` (Runtime with context, store, stream_writer)
- **`ToolCallRequest`**: `.tool_call` (dict: name/args/id), `.tool` (BaseTool|None), `.state`, `.runtime`
- **`AgentState`**: TypedDict, base = `messages: list[AnyMessage]`, extendable via `state_schema`

### Middleware Chain Composition Order (DeepAgent)

```
TodoListMiddleware
  → SkillsMiddleware (if skills provided)
    → FilesystemMiddleware
      → SubAgentMiddleware (if inline subagents)
        → SummarizationMiddleware
          → PatchToolCallsMiddleware
            → [USER MIDDLEWARE] ← insertion point
              → [Harness profile extra_middleware]
                → Anthropic/Bedrock/Fireworks PromptCachingMiddleware
                  → MemoryMiddleware (if memory provided)
                    → HumanInTheLoopMiddleware (if interrupt_on set)
```

Each `wrap_model_call` wraps the next — the outermost middleware's handler calls the next middleware's handler, etc., culminating in the actual LLM call.

### State Management via state_schema

To persist data across turns (e.g., counters), subclass AgentState and set `state_schema`:

```python
class MyState(AgentState):
    turn_count: int = 0

class MyMiddleware(AgentMiddleware):
    state_schema = MyState
    def before_model(self, state, runtime):
        state["turn_count"] += 1
        return None  # Mutating state persists automatically
```

### Async in LangGraph Agent Middleware

Every hook has both sync and async versions (prefixed `a`): `abefore_agent`, `awrap_model_call`, `aafter_agent`, etc. LangGraph automatically calls the async variant when the graph is invoked with `ainvoke()`. The middleware can define only the async version and leave sync unimplemented.

### Source of Truth

Always inspect the actual `langchain.agents.middleware` module for the canonical hook interface. The classes to read:

```python
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ToolCallRequest, Runtime
from langchain_core.messages import AnyMessage
```
