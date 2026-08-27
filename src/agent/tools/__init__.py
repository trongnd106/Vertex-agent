"""Custom business tools for the deep-agent backend, built with LangChain's `@tool`.

These are the "user-supplied" tools passed via `create_deep_agent(tools=[...])`,
which **add** to the built-in filesystem/task tools rather than replacing them
(see docs/phase-0-discovery.md §3.2 / §10).

The docstrings here are model-facing: the LLM sees them as the tool
descriptions, so they start with a one-line intent and stay deterministic.
"""

from __future__ import annotations

from langchain_core.tools import tool

from .order_store import create_ticket, query_order_db

__all__ = ["create_support_ticket", "query_order"]


@tool
def query_order(order_id: str) -> str:
    """Look up a customer order by its id (e.g. 'A-1001') and return its status and line items.

    Returns a human-readable summary, or an error message when the order id is
    unknown. Read-only: it never modifies any data.
    """
    return query_order_db(order_id)


@tool
def create_support_ticket(reporter: str, subject: str, body: str) -> str:
    """Open a new customer-support ticket.

    Args:
        reporter: Name or identifier of the person reporting the issue.
        subject: Short title for the ticket.
        body: Full description of the problem.

    Returns:
        The generated ticket id (e.g. 'T-0001') once the ticket is recorded.
    """
    return create_ticket(reporter, subject, body)
