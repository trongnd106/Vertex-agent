"""Deployment entrypoint for a LangGraph API server.

Phase 8 (``langgraph dockerfile`` / ``langgraph up`` / ``langgraph dev``) needs a
module exposing a **compiled graph at module level** (``graph``), because the
LangGraph server imports the module and reads ``LANGSERVE_GRAPHS``/``graphs``
(keys → ``module:attr``) to wire the HTTP/assistant endpoints.

This is deliberately a THIN wrapper, separate from the single construction point
``src/agent/graph.py::build_agent`` (which stays unchanged / stable — every
other task consumes it directly):

- It builds ONE compiled agent bound to the model named by ``AGENT_MODEL``.
- It does NOT pass ``store``/``checkpointer`` explicitly: ``build_agent`` leaves
  them ``None``, so deepagents resolves them at call time via ``get_store()`` /
  ``get_checkpointer()`` from the executing LangGraph server runtime
  (verified, discovery §5 / §14.3). That lets the LangGraph API server manage
  the Postgres checkpointer + Store (both ``store:`` and ``checkpointer:`` in
  ``langgraph.json`` / server env), rather than us double-managing a second
  connection.

Only run for real when an LLM key/provider is configured (M1). With
``AGENT_MODEL`` unset it falls back to a default so ``langgraph validate`` and a
bare server boot succeed.
"""

from __future__ import annotations

from src.agent.system_prompt import build_system_prompt as _build_system_prompt
from src.config import config

#: Default provider:model used when ``AGENT_MODEL`` is not set. The LangGraph
#: server reaches an LLM provider only when a real key/provider is configured at
#: runtime (M1); this default just lets the module import and the server boot.
DEFAULT_MODEL = "openai:gpt-4o-mini"


def _model_from_env() -> str:
    """Resolve the agent model from the env config.

    Priority:
    1. ``LLM_PROVIDER`` + ``LLM_MODEL`` — split form (e.g. ``LiteLLM`` + ``DeepSeek-V4-Flash``).
       Nếu provider là LiteLLM, dùng ``openai:...`` vì LiteLLM là OpenAI-compatible.
    2. ``AGENT_MODEL`` — explicit combined string (e.g. ``openai:gpt-4o``)
    3. Hard-coded ``DEFAULT_MODEL``
    """
    if config.LLM_PROVIDER and config.LLM_MODEL:
        provider = config.LLM_PROVIDER.lower().replace(" ", "")
        # LiteLLM server là OpenAI-compatible — dùng openai provider
        if provider == "litellm":
            provider = "openai"
        return f"{provider}:{config.LLM_MODEL}"
    explicit = config.AGENT_MODEL
    if explicit:
        return explicit
    return DEFAULT_MODEL


def _build_graph():
    """Compile the agent graph bound to the configured model (import-time).

    Returns a compiled ``StateGraph`` on success, or a minimal echo graph
    as fallback when the real agent fails (no LLM key, broken skills, etc.).
    """
    import importlib  # lazy: deepagents may not be installed

    model = _model_from_env()
    provider_name = config.LLM_PROVIDER or "OpenAI"
    model_name = model.split(":", 1)[1] if ":" in model else model
    system_prompt = _build_system_prompt(
        model_name=model_name,
        provider_name=provider_name,
        show_env_hints=True,
    )
    try:
        graph_mod = importlib.import_module("src.agent.graph")
        build_fn = getattr(graph_mod, "build_agent")
        return build_fn(model=model, system_prompt=system_prompt)
    except Exception as exc:
        logger = importlib.import_module("logging").getLogger(__name__)
        logger.warning("Agent graph build failed (%s); using stub echo graph", exc)
        return _build_stub_graph()


def _build_stub_graph():
    """Build a minimal stub graph that echoes user messages.

    This lets the API server start and respond even when the real agent
    cannot be compiled (missing deepagents, no LLM key, etc.).
    """
    from langchain_core.messages import AIMessage
    from langgraph.graph import MessagesState, StateGraph

    async def echo_node(state: MessagesState) -> MessagesState:
        user_msgs = [m for m in state.get("messages", []) if getattr(m, "role", "") == "user"]
        last = user_msgs[-1] if user_msgs else None
        if last:
            content = getattr(last, "content", "")
            return {"messages": [AIMessage(content=f"[Stub] Received: {content[:200]}")]}
        return state

    stub = StateGraph(MessagesState)
    stub.add_node("echo", echo_node)
    stub.set_entry_point("echo")
    return stub.compile()


#: Module-level compiled graph — what ``langgraph.json``'s ``graphs`` entry
#: references as ``./src/agent/server.py:graph``.
try:
    graph = _build_graph()
except Exception as exc:
    logger = __import__("logging").getLogger(__name__)
    logger.warning("Top-level graph build failed (%s); using stub", exc)
    graph = _build_stub_graph()

__all__ = ["DEFAULT_MODEL", "_model_from_env", "graph"]