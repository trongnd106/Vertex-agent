"""Namespace management for multi-tenant store isolation.

Provides ``NamespaceFactory`` implementations and ``NamespaceManager`` for
resolving namespaces from runtime context with fallback chains.

Supports:
- User-based isolation: ``("memories", user_id)``
- Bot/tenant-based: ``("memories", bot_id, user_id)``
- Global namespace: ``("memories", "global")``
- Access control: namespace-level permissions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src.memory.backend import UserContext
from src.memory.store import BaseStore, InMemoryStore


# ── Namespace resolution ────────────────────────────────────────────────

# Function type that resolves a namespace from context
NamespaceResolver = Callable[..., tuple[str, ...]]


# ── Namespace factory implementations ───────────────────────────────────


def user_namespace(user: UserContext) -> tuple[str, ...]:
    """Create ``("memories", user_id)`` namespace from a user context.

    Args:
        user: User context with user_id.

    Returns:
        Namespace tuple.

    Raises:
        RuntimeError: If user_id is empty.
    """
    if not user.user_id:
        raise RuntimeError("Cannot create user namespace: user_id is empty")
    return ("memories", user.user_id)


def bot_user_namespace(bot_id: str, user: UserContext) -> tuple[str, ...]:
    """Create ``("memories", bot_id, user_id)`` namespace.

    Args:
        bot_id: Bot/tenant identifier.
        user: User context.

    Returns:
        Namespace tuple.
    """
    if not bot_id:
        raise RuntimeError("Cannot create bot namespace: bot_id is empty")
    if not user.user_id:
        raise RuntimeError("Cannot create bot namespace: user_id is empty")
    return ("memories", bot_id, user.user_id)


def global_namespace() -> tuple[str, ...]:
    """Create ``("memories", "global")`` namespace for shared memory.

    Returns:
        Global namespace tuple.
    """
    return ("memories", "global")


# ── Namespace manager ───────────────────────────────────────────────────


@dataclass
class NamespaceRule:
    """A namespace resolution rule with priority.

    Higher priority rules are tried first.
    """

    name: str
    resolver: NamespaceResolver
    priority: int = 0
    description: str = ""


class NamespaceManager:
    """Manages namespace resolution from runtime context with fallback.

    Maintains a list of ``NamespaceRule`` objects ordered by priority.
    When resolving, tries higher-priority rules first and falls back
    through lower-priority ones.

    Controls access at the namespace level via allow/deny lists.
    """

    def __init__(self, store: BaseStore | None = None) -> None:
        self._store = store or InMemoryStore()
        self._rules: list[NamespaceRule] = []
        self._allowed_namespaces: list[tuple[str, ...]] = []
        self._denied_namespaces: list[tuple[str, ...]] = []
        self._namespace_prefix_access: dict[tuple[str, ...], list[str]] = {}
        """Maps namespace prefix -> list of allowed user_ids."""

    # ── Rule management ──────────────────────────────────────────────

    def add_rule(self, rule: NamespaceRule) -> None:
        """Add a namespace resolution rule."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)

    def add_rules(self, rules: list[NamespaceRule]) -> None:
        """Add multiple rules at once."""
        self._rules.extend(rules)
        self._rules.sort(key=lambda r: -r.priority)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name.

        Returns:
            True if the rule was found and removed.
        """
        for i, rule in enumerate(self._rules):
            if rule.name == name:
                self._rules.pop(i)
                return True
        return False

    # ── Namespace resolution ─────────────────────────────────────────

    def resolve(self, **context: Any) -> tuple[str, ...]:
        """Resolve a namespace from context using registered rules.

        Tries rules in priority order. The first rule whose resolver
        succeeds (does not raise) wins.

        Args:
            **context: Keyword arguments passed to each resolver.

        Returns:
            The resolved namespace tuple.

        Raises:
            RuntimeError: If no rule can resolve a namespace.
        """
        errors: list[str] = []
        for rule in self._rules:
            try:
                ns = rule.resolver(**context)
                if ns and len(ns) >= 2:  # minimum: ("memories", something)
                    if self._check_access(ns, context):
                        return ns
            except Exception as e:
                errors.append(f"{rule.name}: {e}")
                continue

        raise RuntimeError(
            f"Cannot resolve namespace: all rules failed. Errors: {'; '.join(errors)}"
        )

    # ── Access control ───────────────────────────────────────────────

    def allow_namespace(self, namespace: tuple[str, ...]) -> None:
        """Add a namespace to the allow list."""
        if namespace not in self._allowed_namespaces:
            self._allowed_namespaces.append(namespace)

    def deny_namespace(self, namespace: tuple[str, ...]) -> None:
        """Add a namespace to the deny list."""
        if namespace not in self._denied_namespaces:
            self._denied_namespaces.append(namespace)

    def grant_access(self, namespace_prefix: tuple[str, ...], user_id: str) -> None:
        """Grant a user access to a namespace prefix.

        Args:
            namespace_prefix: e.g. ``("memories", "bot_1")``.
            user_id: User to grant access.
        """
        self._namespace_prefix_access.setdefault(namespace_prefix, [])
        if user_id not in self._namespace_prefix_access[namespace_prefix]:
            self._namespace_prefix_access[namespace_prefix].append(user_id)

    def revoke_access(self, namespace_prefix: tuple[str, ...], user_id: str) -> None:
        """Revoke a user's access to a namespace prefix."""
        users = self._namespace_prefix_access.get(namespace_prefix)
        if users and user_id in users:
            users.remove(user_id)

    def _check_access(self, namespace: tuple[str, ...], context: dict[str, Any]) -> bool:
        """Check if the requested namespace is accessible.

        Checks in order:
        1. If denied_namespaces contains this namespace or prefix → deny
        2. If allowed_namespaces is non-empty and this ns not in it → deny
        3. If namespace_prefix_access restricts access → check user
        """
        # Check deny list
        for denied in self._denied_namespaces:
            if namespace[: len(denied)] == denied:
                return False

        # Check allow list (if non-empty, must be in it)
        if self._allowed_namespaces:
            allowed = False
            for allowed_ns in self._allowed_namespaces:
                if namespace[: len(allowed_ns)] == allowed_ns:
                    allowed = True
                    break
            if not allowed:
                return False

        # Check per-prefix user-level access
        for prefix, allowed_users in self._namespace_prefix_access.items():
            if namespace[: len(prefix)] == prefix:
                user_id = context.get("user_id", "")
                if user_id not in allowed_users:
                    return False

        return True

    # ── Utility ──────────────────────────────────────────────────────

    def build_default(self) -> NamespaceManager:
        """Build a standard set of rules for common use cases.

        Configures three default rules:
        1. Bot/user isolation (highest priority)
        2. User isolation (medium priority)
        3. Global fallback (lowest priority)
        """
        self.add_rules([
            NamespaceRule(
                name="bot_user",
                resolver=lambda **ctx: bot_user_namespace(
                    ctx.get("bot_id", ""), ctx.get("user", UserContext(user_id=""))
                ),
                priority=100,
                description="Isolate by bot + user",
            ),
            NamespaceRule(
                name="user",
                resolver=lambda **ctx: user_namespace(
                    ctx.get("user", UserContext(user_id=ctx.get("user_id", "")))
                ),
                priority=50,
                description="Isolate by user",
            ),
            NamespaceRule(
                name="global",
                resolver=lambda **ctx: global_namespace(),
                priority=10,
                description="Global fallback",
            ),
        ])
        return self


__all__ = [
    "NamespaceManager",
    "NamespaceResolver",
    "NamespaceRule",
    "bot_user_namespace",
    "global_namespace",
    "user_namespace",
]