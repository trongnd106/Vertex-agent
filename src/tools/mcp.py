"""MCP (Model Context Protocol) tool integration.

Provides an MCP client, tool adapter, and lifecycle management for
discovering and executing tools exposed by MCP servers.

The MCP integration follows the Model Context Protocol specification:
https://spec.modelcontextprotocol.io/

At runtime, if the ``mcp`` package is not installed, all MCP operations
raise a descriptive ``ImportError``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from src.tools.filesystem import ToolResult
from src.tools.registry import ToolSpec

logger = logging.getLogger(__name__)

try:
    import mcp as mcp_module
    from mcp.client.stdio import stdio_client
    from mcp.types import CallToolResult as MCPCallToolResult

    _HAS_MCP = True

    # Guard: check we have the version we expect
    if not hasattr(mcp_module, "Tool"):
        _HAS_MCP = False
        _MCP_IMPORT_ERROR = "mcp module missing 'Tool' type — upgrade with 'pip install mcp>=1.0'"

except ImportError:
    _HAS_MCP = False
    _MCP_IMPORT_ERROR = (
        "mcp package is not installed.  Install with: pip install mcp"
    )


# ── MCP Server configuration ────────────────────────────────────────────


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server process.

    To connect to a stdio-based MCP server, provide the command and arguments::

        MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
    """

    name: str
    """Human-readable name for this server."""
    command: str
    """Command to launch the server process (e.g. ``npx``, ``python``)."""
    args: list[str] = field(default_factory=list)
    """Arguments for the command."""
    env: dict[str, str] | None = None
    """Additional environment variables (merged with current env)."""
    cwd: str | None = None
    """Working directory for the server process."""
    transport: str = "stdio"
    """Transport type. Currently only ``stdio`` is supported."""


@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


# ── MCP Client ──────────────────────────────────────────────────────────


class MCPClientState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class MCPClient:
    """Manages a connection to a single MCP server.

    Handles lifecycle (start → connect → list_tools → call_tool → shutdown).
    """

    def __init__(self, config: MCPServerConfig) -> None:
        if not _HAS_MCP:
            raise ImportError(_MCP_IMPORT_ERROR)

        self.config = config
        self.state = MCPClientState.DISCONNECTED
        self._process: subprocess.Popen[bytes] | None = None
        self._session: Any = None
        self._read: Any = None
        self._write: Any = None
        self._lock = threading.Lock()
        self._tools_cache: list[MCPTool] | None = None

    def connect(self) -> None:
        """Start the server process and establish an MCP session.

        Raises:
            RuntimeError: If connection fails.
        """
        if self.state == MCPClientState.CONNECTED:
            return

        self.state = MCPClientState.CONNECTING

        try:
            server_params = type(
                "ServerParameters",
                (),
                {
                    "command": self.config.command,
                    "args": self.config.args,
                    "env": self.config.env,
                    "cwd": self.config.cwd,
                },
            )()

            # Use stdio_client from mcp
            stdio = stdio_client(server_params)
            self._read, self._write = stdio.__enter__()

            # Initialize session
            from mcp.client.session import ClientSession

            self._session = ClientSession(self._read, self._write)
            init_result = self._session.initialize()

            self.state = MCPClientState.CONNECTED
            self._tools_cache = None  # invalidate on reconnect
        except Exception as e:
            self.state = MCPClientState.ERROR
            raise RuntimeError(f"MCP connection failed for {self.config.name}: {e}")

    def list_tools(self) -> list[MCPTool]:
        """List tools provided by this MCP server.

        Returns:
            List of ``MCPTool`` instances.
        """
        if self.state != MCPClientState.CONNECTED:
            raise RuntimeError(f"MCP client not connected (state={self.state.value})")

        if self._tools_cache is not None:
            return self._tools_cache

        try:
            result = self._session.list_tools()
            tools: list[MCPTool] = []
            for tool in result.tools:
                tools.append(
                    MCPTool(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema,
                        server_name=self.config.name,
                    )
                )
            self._tools_cache = tools
            return tools
        except Exception as e:
            raise RuntimeError(f"Failed to list MCP tools: {e}")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call an MCP tool by name.

        Args:
            name: Tool name.
            arguments: Tool arguments as a dict.

        Returns:
            ``ToolResult``.
        """
        if self.state != MCPClientState.CONNECTED:
            raise RuntimeError(f"MCP client not connected (state={self.state.value})")

        try:
            result: Any = self._session.call_tool(name, arguments)

            if isinstance(result, MCPCallToolResult):
                text_parts: list[str] = []
                is_error = result.isError or False
                for content in result.content:
                    if hasattr(content, "text") and content.text:
                        text_parts.append(content.text)
                return ToolResult(
                    success=not is_error,
                    data="\n".join(text_parts) if text_parts else "(no content)",
                    metadata={"mcp_server": self.config.name, "mcp_tool": name},
                )

            return ToolResult(success=True, data=str(result))
        except Exception as e:
            return ToolResult(success=False, error=f"MCP tool call failed: {e}")

    def shutdown(self) -> None:
        """Shutdown the MCP session and process."""
        with self._lock:
            try:
                if self._session:
                    self._session.close()
            except Exception:
                pass
            try:
                if self._process:
                    self._process.terminate()
                    self._process.wait(timeout=5)
            except Exception:
                pass

            self._session = None
            self._read = None
            self._write = None
            self._process = None
            self.state = MCPClientState.DISCONNECTED
            self._tools_cache = None

    def __enter__(self) -> MCPClient:
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()


# ── MCP Manager ─────────────────────────────────────────────────────────


class MCPManager:
    """Manages multiple MCP server connections.

    Provides a unified view of all MCP tools across connected servers and
    can feed tools into a ``ToolRegistry``.
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._lock = threading.Lock()

    def add_server(self, config: MCPServerConfig) -> MCPClient:
        """Add and connect an MCP server.

        Args:
            config: Server configuration.

        Returns:
            The connected ``MCPClient``.
        """
        client = MCPClient(config)
        client.connect()
        with self._lock:
            self._clients[config.name] = client
        return client

    def remove_server(self, name: str) -> None:
        """Disconnect and remove an MCP server."""
        with self._lock:
            client = self._clients.pop(name, None)
        if client:
            client.shutdown()

    def list_all_tools(self) -> list[MCPTool]:
        """List all tools from all connected servers."""
        tools: list[MCPTool] = []
        with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            try:
                tools.extend(client.list_tools())
            except RuntimeError:
                continue
        return tools

    def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call a tool on a specific server.

        Args:
            server_name: MCP server name.
            tool_name: Tool name.
            arguments: Tool arguments.

        Returns:
            ``ToolResult``.
        """
        with self._lock:
            client = self._clients.get(server_name)
        if not client:
            return ToolResult(success=False, error=f"Unknown MCP server: {server_name}")
        return client.call_tool(tool_name, arguments)

    def to_registry_entries(self) -> list[ToolSpec]:
        """Convert all MCP tools to ``ToolSpec`` entries for registration.

        Each MCP tool is wrapped in a closure that calls through the
        manager.
        """
        entries: list[ToolSpec] = []
        for tool in self.list_all_tools():
            server_name = tool.server_name

            def _make_fn(
                _tool_name: str = tool.name,
                _server: str = server_name,
            ) -> Callable[..., ToolResult]:
                def _fn(**kwargs: Any) -> ToolResult:
                    return self.call_tool(_server, _tool_name, kwargs)

                _fn.__name__ = _tool_name
                _fn.__doc__ = tool.description
                return _fn

            entries.append(
                ToolSpec(
                    name=f"{tool.server_name}:{tool.name}",
                    description=tool.description,
                    fn=_make_fn(),
                    category="mcp",
                    tags=["mcp", tool.server_name],
                    metadata={"input_schema": tool.input_schema, "server": tool.server_name},
                )
            )
        return entries

    def shutdown_all(self) -> None:
        """Shutdown all connected MCP servers."""
        with self._lock:
            names = list(self._clients.keys())
        for name in names:
            self.remove_server(name)


__all__ = [
    "MCPClient",
    "MCPClientState",
    "MCPManager",
    "MCPServerConfig",
    "MCPTool",
    "_HAS_MCP",
]