"""Role-based tool limiting via deepagents `HarnessProfile`.

Plan §4.2 makes the per-role tool list a **hard boundary**: agents fronting
end-users must not be able to reach the shell (`execute`), while trusted
operators may keep every built-in tool. The mechanism is deepagents'
`register_harness_profile(key, HarnessProfile(excluded_tools=...))`, resolved
per model inside `create_deep_agent` (see
`deepagents/profiles/harness/harness_profiles.py::_harness_profile_for_model`
and `deepagents/graph.py`).

Registrations are **additive**: re-registering under the same key (or across a
provider + exact-model key) unions the excluded-tool sets rather than replacing
them. Role profiles should therefore be registered once at app startup.
"""

from __future__ import annotations

from deepagents import HarnessProfile, register_harness_profile

CUSTOMER_SUPPORT_ROLE = "customer-support"
OPERATOR_ROLE = "operator"

# A customer-support agent fronting end users must never reach the shell.
_CUSTOMER_SUPPORT_EXCLUDED: frozenset[str] = frozenset({"execute"})
# A trusted operator may keep every built-in tool.
_OPERATOR_EXCLUDED: frozenset[str] = frozenset()


def register_customer_support_role() -> None:
    """Register the `customer-support` harness profile, excluding `execute`.

    Calling this more than once is safe: `register_harness_profile` merges
    additively (excluded sets union), so the result is unchanged.
    """
    register_harness_profile(
        CUSTOMER_SUPPORT_ROLE,
        HarnessProfile(excluded_tools=_CUSTOMER_SUPPORT_EXCLUDED),
    )


def register_operator_role() -> None:
    """Register the `operator` harness profile with no excluded tools.

    Operators keep every built-in tool (filesystem ops + `execute`). When
    paired with a sandboxed backend (see `src/agent/tools/sandbox.py`), a
    production operator's `execute` runs in an isolated sandbox rather than
    on the raw host.
    """
    register_harness_profile(
        OPERATOR_ROLE,
        HarnessProfile(excluded_tools=_OPERATOR_EXCLUDED),
    )


def register_all_roles() -> None:
    """Register every known role. Idempotent."""
    register_customer_support_role()
    register_operator_role()


__all__ = [
    "CUSTOMER_SUPPORT_ROLE",
    "OPERATOR_ROLE",
    "register_all_roles",
    "register_customer_support_role",
    "register_operator_role",
]
