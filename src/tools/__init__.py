"""Tool system for the agent framework.

Provides built-in filesystem tools, a tool registry, MCP integration,
sandboxed execution, permission/audit/HITL, and tool discovery.
"""

from src.tools.discovery import (
    ToolCallRecord,
    ToolDescription,
    ToolDiscovery,
    ToolSelector,
    ToolStatistics,
)
from src.tools.filesystem import (
    FILESYSTEM_TOOLS,
    FilePermission,
    ToolResult,
    delete_file,
    edit_file,
    execute_command,
    glob_files,
    grep_files,
    ls,
    read_file,
    write_file,
)
from src.tools.mcp import (
    MCPClient,
    MCPClientState,
    MCPManager,
    MCPServerConfig,
    MCPTool,
)
from src.tools.permissions import (
    AuditEntry,
    AuditLog,
    FilesystemPermission,
    HITLDecision,
    HITLRequest,
    HumanInTheLoop,
    PermissionMode,
    Role,
    RoleBasedAccess,
)
from src.tools.registry import (
    ToolRegistry,
    ToolSpec,
    chain_tools,
    get_default_registry,
    reset_default_registry,
)
from src.tools.sandbox import (
    BaseSandbox,
    DockerSandbox,
    LocalShellSandbox,
    PythonSandbox,
    ResourceLimits,
    SandboxResult,
)

__all__ = [
    # Filesystem
    "FILESYSTEM_TOOLS",
    "FilePermission",
    "ToolResult",
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "delete_file",
    "glob_files",
    "grep_files",
    "execute_command",
    # Registry
    "ToolRegistry",
    "ToolSpec",
    "chain_tools",
    "get_default_registry",
    "reset_default_registry",
    # MCP
    "MCPClient",
    "MCPClientState",
    "MCPManager",
    "MCPServerConfig",
    "MCPTool",
    # Sandbox
    "BaseSandbox",
    "DockerSandbox",
    "LocalShellSandbox",
    "PythonSandbox",
    "ResourceLimits",
    "SandboxResult",
    # Permissions
    "AuditEntry",
    "AuditLog",
    "FilesystemPermission",
    "HITLDecision",
    "HITLRequest",
    "HumanInTheLoop",
    "PermissionMode",
    "Role",
    "RoleBasedAccess",
    # Discovery
    "ToolCallRecord",
    "ToolDescription",
    "ToolDiscovery",
    "ToolSelector",
    "ToolStatistics",
]