"""Research subagent with isolated context (plan 4.3 "Subagent context isolation").

Long, context-heavy work (deep lookups, reading long documents) is delegated to
a dedicated subagent via the built-in `task` tool. The subagent runs in its own
isolated graph invocation: its internal working messages (tool calls, stores)
are built in a fresh state (`deepagents/middleware/subagents.py` line ~538) and
only the subagent's final text is returned to the main agent as a `ToolMessage`
(`_return_command_with_state_update`, line ~476). The main agent's message list
therefore never fills with the subagent's intermediate scratch.

The subagent intentionally carries the narrowest tool set it needs — a
read-only order lookup — so it cannot reach the filesystem, shell, or the
main agent's business-mutation tools.
"""

from __future__ import annotations

from deepagents import SubAgent

from src.agent.tools import query_order

# A marker unique to this subagent's system prompt (used by tests to assert the
# internal context never leaks into the main conversation).
SUBAGENT_SYSTEM_MARKER = "INTERNAL-CODE-9X"

RESEARCH_SUBAGENT: SubAgent = {
    "name": "research",
    "description": (
        "Research an order by id and return a concise, self-contained summary "
        " of its line items and status. Use for any order-detail lookup."
    ),
    "system_prompt": (
        f"{SUBAGENT_SYSTEM_MARKER}\n"
        "You are an order-research specialist. Given a request, look up the "
        "order with query_order and return ONLY a short, self-contained "
        "summary of what you found. Do not speculate or add extra prose."
    ),
    "tools": [query_order],
}

__all__ = [
    "RESEARCH_SUBAGENT",
    "SUBAGENT_SYSTEM_MARKER",
    "build_research_subagent",
]


def build_research_subagent() -> SubAgent:
    """Return the research subagent spec for `create_deep_agent(subagents=[...])`.

    Returns a fresh dict each call so callers can tweak it without mutating the
    module-level default.
    """
    return dict(RESEARCH_SUBAGENT)
