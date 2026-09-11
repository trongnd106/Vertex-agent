"""Agent construction for the vertex-agent backend.

``build_agent`` (src/agent/graph.py) is the central factory threading the
deep-agent harness with the project's Store-backed long-term memory, per-user
context, custom tools, and optional checkpointer (Tasks 2, 4, 5; consumed by
Tasks 6-8).

All names are imported lazily so the package can be imported even when
optional dependencies (deepagents) are not installed.
"""

from __future__ import annotations

import importlib

_MODULE = "src.agent.graph"


def __getattr__(name: str):
    """Lazy-import from ``graph`` on first access."""
    mod = importlib.import_module(_MODULE)
    if hasattr(mod, name):
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DEFAULT_CONTEXT_SCHEMA",
    "DEFAULT_TOOLS",
    "MEMORY_GUIDANCE",
    "build_agent",
    "build_system_prompt",
]