"""Agent construction for the vertex-agent backend.

``build_agent`` (src/agent/graph.py) is the central factory threading the
deep-agent harness with the project's Store-backed long-term memory, per-user
context, custom tools, and optional checkpointer (Tasks 2, 4, 5; consumed by
Tasks 6-8).
"""

from .graph import (
    DEFAULT_CONTEXT_SCHEMA,
    DEFAULT_TOOLS,
    MEMORY_GUIDANCE,
    build_agent,
    build_system_prompt,
)

__all__ = [
    "DEFAULT_CONTEXT_SCHEMA",
    "DEFAULT_TOOLS",
    "MEMORY_GUIDANCE",
    "build_agent",
    "build_system_prompt",
]
