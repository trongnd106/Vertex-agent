# Fix: Agent Invoke crash + Loss of conversation memory

## Problem

### 1. `'NoneType' object has no attribute 'aget'` on POST /invoke

**Root cause:** Graph is compiled without explicit `checkpointer`/`store` in `build_agent()`. When the FastAPI server calls `graph.ainvoke()` directly (not through LangGraph server), there is no LangGraph runtime context to inject store/checkpointer, so `get_store()` returns `None` → crash on `.aget()`.

### 2. Agent doesn't remember previous messages

**Root cause 1:** Each `/invoke` call only sends the **current** user message, not the full conversation history:
```python
input_state = {
    "messages": [{"role": "user", "content": request.message}],
}
```
No previous messages from the thread are loaded.

**Root cause 2:** No checkpointer is configured when running standalone FastAPI, so thread states are never saved or restored.

## Solution

### Step 1 — Add `MemorySaver` as default checkpointer & `InMemoryStore` as default store in the API server

In `src/api/server.py`, during `lifespan`:
- Create an in-memory `MemorySaver` checkpointer
- Create an in-memory `BaseStore`
- Pass them to `build_agent()` or attach them to the compiled graph

### Step 2 — Load conversation history before invoke

In `/invoke` endpoint:
- Before sending the new message, read `server_state.graph.aget_state()` to get existing messages for this `thread_id`
- Prepend those messages to `input_state["messages"]` so the agent sees the full history

### Step 3 — Handle errors gracefully

- Wrap the checkpointer/store attachment so the server still works even if these are not available