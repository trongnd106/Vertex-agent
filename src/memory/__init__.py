"""Memory & Persistence system.

Provides checkpoint-based short-term memory, long-term store,
memory middleware, namespace management, and a dreaming system
for background self-improvement.
"""

from src.memory.backend import (
    CompositeBackend,
    NamespaceFactory,
    StoreBackend,
    UserContext,
)
from src.memory.checkpoint import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    InMemorySaver,
    PendingWrite,
    TimeTravel,
    TimeTravelResult,
)
# Dreaming system is a separate sub-package — import from src.memory.dreaming directly
from src.memory.memory_middleware import (
    DEFAULT_MEMORY_FILES,
    MemoryFile,
    MemoryMiddleware,
    strip_html_comments,
)
from src.memory.namespace import (
    NamespaceManager,
    NamespaceResolver,
    NamespaceRule,
    bot_user_namespace,
    global_namespace,
    user_namespace,
)
from src.memory.store import (
    BaseStore,
    InMemoryStore,
    Item,
    PostgresStore,
    SearchResult,
    StoreFilter,
    get_store,
    close_store,
)

__all__ = [
    # Checkpoint
    "BaseCheckpointSaver",
    "Checkpoint",
    "CheckpointMetadata",
    "InMemorySaver",
    "PendingWrite",
    "TimeTravel",
    "TimeTravelResult",
    # Store
    "BaseStore",
    "InMemoryStore",
    "Item",
    "PostgresStore",
    "SearchResult",
    "StoreFilter",
    # Backend
    "CompositeBackend",
    "NamespaceFactory",
    "StoreBackend",
    "UserContext",
    # Memory middleware
    "DEFAULT_MEMORY_FILES",
    "MemoryFile",
    "MemoryMiddleware",
    "strip_html_comments",
    # Namespace
    "NamespaceManager",
    "NamespaceResolver",
    "NamespaceRule",
    "bot_user_namespace",
    "global_namespace",
    "user_namespace",
    "get_store",
    "close_store",
    ]