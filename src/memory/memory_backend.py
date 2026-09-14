"""Long-term memory backend: a per-user Store namespace mounted at ``/memory/``.

Phase 5 keeps long-term memory *inside the agent's own filesystem tooling*:
the agent writes and reads a "virtual file" ``/memory/notes.md`` through the
built-in ``write_file`` / ``read_file`` tools, which the hardware backend
redirects into LangGraph's cross-thread ``BaseStore``. No extra memory tool is
needed — filesystem-as-memory (plan §4.5).

The assembly (verified against the installed 0.7.9 source, see
`docs/phase-0-discovery.md` §5–§6):

- ``StoreBackend(namespace=..., store=None)`` — the ``store=None`` path calls
  ``langgraph.config.get_store()`` at call time, so the graph **must** be bound
  to a store via ``create_deep_agent(store=store, ...)`` (or ``build_agent``).
- ``CompositeBackend(default=FilesystemBackend(root_dir="."), routes=...)`` —
  NOT a single dict argument. Only the ``/memory/`` route is mounted here; the
  skills stay on the default route and load through ``skills=["/skills/"]``.

User isolation — live-probe verdict (Task 5): ``runtime.context.user_id``
**does** carry a per-user id in 0.7.9, but only when (a) ``context_schema`` is
a ``dataclass``/pydantic model (a ``TypedDict`` renders ``Runtime.context`` as a
plain ``dict`` with no attribute access) and (b) the value is supplied through
``invoke(..., context=UserContext(user_id=...))`` — the ``config.configurable``
path is a no-op for context. ``MULTI_USER`` therefore reflects the *real*
behaviour tested in `tests/test_long_term_memory.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from langgraph.store.base import BaseStore

if TYPE_CHECKING:
    from deepagents.backends.composite import CompositeBackend
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.backends.store import NamespaceFactory, StoreBackend

MEMORY_ROUTE = "/memory/"
"""Path prefix that routes into the Store-backed long-term memory."""

MEMORY_NOTES_PATH = "/memory/notes.md"
"""Conventional location of the accumulated long-term notes file."""


@dataclass
class UserContext:
    """LangGraph ``context_schema`` carrying the current user id.

    Probing showed a ``dataclass`` (not a plain ``TypedDict``) is required for
    ``runtime.context.user_id`` attribute access: LangGraph coerces a dict
    back into the schema type, and a ``TypedDict`` produces a plain ``dict``
    with no attribute access. A ``dataclass`` preserves attribute access.
    """

    user_id: str


USER_CONTEXT_SCHEMA: type[UserContext] = UserContext
"""Re-export for use as ``context_schema`` in ``create_deep_agent``."""


#: Live-probe result: ``runtime.context.user_id`` is populated for multi-user
#: namespaces ``("memories", user_id)`` (live-probe verified); a fixed-user
#: fallback was NOT needed.
MULTI_USER = True


def make_namespace_factory() -> "NamespaceFactory":
    """Return the per-user namespace factory used by the ``/memory/`` Store.

    The factory reads ``runtime.context.user_id`` and emits the plan's
    ``("memories", user_id)`` namespace, so user A and user B get separate
    long-term memories while two sessions of the *same* user share one. The
    ``StoreBackend`` calls it at write/read time with the resolved ``Runtime``
    (or ``None`` outside a graph execution).

    Raises:
        RuntimeError: when no ``Runtime`` is available or ``context`` is
            ``None`` (i.e. the graph was invoked without
            ``context=UserContext(user_id=...)``).
    """

    def _namespace(runtime: object | None) -> tuple[str, ...]:
        if runtime is None or getattr(runtime, "context", None) is None:
            msg = (
                "No user context available for /memory/: the graph must be "
                "invoked with context=UserContext(user_id=...) (and created "
                "with context_schema=USER_CONTEXT_SCHEMA) so the Store "
                "namespace can be scoped per user."
            )
            raise RuntimeError(msg)
        return ("memories", runtime.context.user_id)

    return _namespace


def build_memory_filesystem(
    user_id_resolver: "NamespaceFactory | None" = None,
    store: BaseStore | None = None,
) -> "CompositeBackend":
    """Assemble the agent filesystem: disk default + Store-backed ``/memory/``.

    Args:
        user_id_resolver: ``NamespaceFactory`` for the ``/memory/`` route.
            Defaults to :func:`make_namespace_factory` (per-user namespaces via
            the runtime context — see module docstring for the probe verdict).
        store: Optional explicit ``BaseStore`` for ``StoreBackend``. ``None``
            (default) makes the Store resolve at call time from the graph's
            execution context via ``get_store()`` — the graph **must** be built
            with ``create_deep_agent(store=store, ...)``.

    Returns:
        A ``CompositeBackend`` routing ``/memory/*`` into the Store and every
        other path (e.g. ``/skills/*``) to the on-disk ``FilesystemBackend``.
    """
    from deepagents.backends.composite import CompositeBackend
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.backends.local_shell import LocalShellBackend
    from deepagents.backends.store import StoreBackend

    store_backend = StoreBackend(
        namespace=user_id_resolver or make_namespace_factory(),
        store=store,
    )
    return CompositeBackend(
        default=LocalShellBackend(root_dir="."),
        routes={MEMORY_ROUTE: store_backend},
    )


__all__ = [
    "MEMORY_NOTES_PATH",
    "MEMORY_ROUTE",
    "MULTI_USER",
    "USER_CONTEXT_SCHEMA",
    "UserContext",
    "build_memory_filesystem",
    "make_namespace_factory",
]