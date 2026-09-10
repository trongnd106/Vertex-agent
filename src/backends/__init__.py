"""Backend infrastructure — storage, session state, config, database.

Sub-packages and modules:

- ``protocol`` — BackendProtocol, SandboxBackendProtocol, BaseSandbox, FileInfo
- ``implementations`` — StateBackend, FilesystemBackend, CompositeBackend
- ``session`` — SessionStateBackend, InMemorySessionBackend, RedisSessionBackend,
                 DatabaseSessionBackend, VariableScope, SessionVariable
- ``config`` — ConfigManager, ProviderConfig, AgentConfig, DeploymentConfig,
               ConfigWatcher, create_default_config
- ``database`` — DatabaseManager, MigrationManager, create_checkpointer_tables,
                 create_pgvector_extension, BackupStrategy
- ``sandboxed`` — LocalShellBackend, ContainerSandbox, RoleBasedSandboxSelector,
                  LangSmithSandbox
"""

from src.backends.config import (
    AgentConfig,
    ConfigLayer,
    ConfigManager,
    ConfigWatcher,
    DeploymentConfig,
    ProviderConfig,
    create_default_config,
)
from src.backends.database import (
    BackupStrategy,
    DatabaseConfig,
    DatabaseManager,
    MigrationManager,
    create_checkpointer_tables,
    create_pgvector_extension,
    create_session_tables,
)
from src.backends.implementations import (
    CompositeBackend,
    FilesystemBackend,
    StateBackend,
)
from src.backends.protocol import (
    BackendProtocol,
    BackendResult,
    BaseSandbox,
    FileInfo,
    SandboxBackendProtocol,
)
from src.backends.sandboxed import (
    ContainerSandbox,
    LangSmithSandbox,
    LocalShellBackend,
    RoleBasedSandboxSelector,
    SandboxType,
)
from src.backends.session import (
    DatabaseSessionBackend,
    InMemorySessionBackend,
    RedisSessionBackend,
    SessionStateBackend,
    SessionVariable,
    VariableScope,
)

__all__ = [
    # protocol
    "BackendProtocol",
    "BackendResult",
    "BaseSandbox",
    "FileInfo",
    "SandboxBackendProtocol",
    # implementations
    "CompositeBackend",
    "FilesystemBackend",
    "StateBackend",
    # session
    "DatabaseSessionBackend",
    "InMemorySessionBackend",
    "RedisSessionBackend",
    "SessionStateBackend",
    "SessionVariable",
    "VariableScope",
    # config
    "AgentConfig",
    "ConfigLayer",
    "ConfigManager",
    "ConfigWatcher",
    "DeploymentConfig",
    "ProviderConfig",
    "create_default_config",
    # database
    "BackupStrategy",
    "DatabaseConfig",
    "DatabaseManager",
    "MigrationManager",
    "create_checkpointer_tables",
    "create_pgvector_extension",
    "create_session_tables",
    # sandboxed
    "ContainerSandbox",
    "LangSmithSandbox",
    "LocalShellBackend",
    "RoleBasedSandboxSelector",
    "SandboxType",
]