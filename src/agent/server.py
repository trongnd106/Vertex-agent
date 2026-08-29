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

import os

from src.agent.graph import build_agent

#: Default provider:model used when ``AGENT_MODEL`` is not set. The LangGraph
#: server reaches an LLM provider only when a real key/provider is configured at
#: runtime (M1); this default just lets the module import and the server boot.
DEFAULT_MODEL = "openai:gpt-4o-mini"


def _model_from_env() -> str:
    """Resolve the agent model from the ``AGENT_MODEL`` env var."""
    return os.environ.get("AGENT_MODEL") or DEFAULT_MODEL


def _build_graph():
    """Compile the agent graph bound to the configured model (import-time)."""
    return build_agent(model=_model_from_env())


#: Module-level compiled graph — what ``langgraph.json``'s ``graphs`` entry
#: references as ``./src/agent/server.py:graph``.
graph = _build_graph()

__all__ = ["DEFAULT_MODEL", "graph"]
