"""In-memory business data store backing the custom order/support tools.

Deliberately minimal and deterministic so the tools (and the deep-agent tool
loop in tests) can run with no network and no LLM. A real deployment would
swap these module-level collections for a database/service client, keeping the
tool signatures stable.
"""

from __future__ import annotations

import itertools

# order_id -> order info dict (status, item, quantity, unit price)
_ORDERS: dict[str, dict[str, str | int | float]] = {
    "A-1001": {"status": "shipped", "item": "Ergonomic Keyboard", "quantity": 1, "total_usd": 89.0},
    "A-1002": {"status": "processing", "item": "Mechanical Mouse", "quantity": 2, "total_usd": 119.8},
    "A-1003": {"status": "delivered", "item": "USB-C Hub", "quantity": 1, "total_usd": 42.5},
}

# tickets: list of dicts {id, reporter, subject, body, status}
_TICKETS: list[dict[str, str]] = []

_ticket_counter = itertools.count(1)


def query_order_db(order_id: str) -> str:
    """Return a human-readable snapshot of one order, or an error string."""
    order = _ORDERS.get(order_id)
    if order is None:
        return f"No order found for id '{order_id}'."
    return (
        f"Order {order_id} ({order['status']}): {order['quantity']}x "
        f"{order['item']} — ${order['total_usd']} total."
    )


def create_ticket(reporter: str, subject: str, body: str) -> str:
    """Append a new support ticket and return its generated id."""
    ticket_id = f"T-{next(_ticket_counter):04d}"
    _TICKETS.append(
        {
            "id": ticket_id,
            "reporter": reporter,
            "subject": subject,
            "body": body,
            "status": "open",
        }
    )
    return ticket_id


def list_tickets() -> list[dict[str, str]]:
    """Return every recorded ticket (for tests / debugging)."""
    return list(_TICKETS)


def reset_store() -> None:
    """Reset module state so tests are isolated from each other.

    Exported for tests only; not a tool.
    """
    _TICKETS.clear()
    globals()["_ticket_counter"] = itertools.count(1)


__all__ = [
    "create_ticket",
    "list_tickets",
    "query_order_db",
    "reset_store",
]
