"""Helper for connecting the deep-agent backend to MCP servers.

Wraps `langchain_mcp_adapters.client.MultiServerMCPClient` and hands back the
LangChain `BaseTool` list to pass into `create_deep_agent(tools=[...])`.

The implementation is deliberately narrow (YAGNI): it supports a **stdio**
transport against the in-repo fixture server (`tests/fixtures/mcp_server.py`),
which satisfies ruling M5 (no external MCP service exists in this repo). To
add SSE/HTTP servers later, extend the `connections` dict with the matching
connection spec from `langchain_mcp_adapters.sessions`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

# stdio transports are async (the underlying `ClientSession` is an async
# context manager), so every call here is `async def`.
DEFAULT_SERVER_NAME = "fixture-mcp"


def default_mcp_server_command() -> list[str]:
    """Return the `[command, ...args]` needed to launch the fixture server."""
    repo_root = Path(__file__).resolve().parents[3]
    server_path = repo_root / "tests" / "fixtures" / "mcp_server.py"
    return [sys.executable, str(server_path)]


def build_stdio_connection(
    command: list[str] | None = None,
) -> dict:
    """Return the `connections` dict for `MultiServerMCPClient` (stdio)."""
    cmd = command if command is not None else default_mcp_server_command()
    return {
        DEFAULT_SERVER_NAME: {
            "transport": "stdio",
            "command": cmd[0],
            "args": cmd[1:],
        }
    }


def connect_mcp(
    connections: dict | None = None,
    *,
    tool_name_prefix: bool = True,
    server_name: str | None = None,
) -> MultiServerMCPClient:
    """Instantiate an MCP client for the given (default: fixture) connections.

    Args:
        connections: Optional `connections` dict for `MultiServerMCPClient`.
            Defaults to a stdio connection launching the in-repo fixture.
        tool_name_prefix: When True, MCP tools are namespaced with the server
            name (e.g. ``fixture-mcp_get_weather``). Default is True.
        server_name: Limit `get_tools` to a single server; None means all.

    Returns:
        A configured `MultiServerMCPClient`. Call `await client.get_tools(...)`
        to obtain the `BaseTool` list, then pass it to `create_deep_agent`.
    """
    conns = connections if connections is not None else build_stdio_connection()
    return MultiServerMCPClient(
        conns,
        tool_name_prefix=tool_name_prefix,
    )


async def get_mcp_tools(client: MultiServerMCPClient, *, server_name: str | None = None) -> list[BaseTool]:
    """Fetch the `BaseTool` list from an MCP client.

    Args:
        client: An open `MultiServerMCPClient`.
        server_name: Optional single-server name; None returns tools from all
            connected servers.

    Returns:
        The LangChain tools to pass into `create_deep_agent(tools=[...])`.
    """
    return await client.get_tools(server_name=server_name)


__all__ = [
    "DEFAULT_SERVER_NAME",
    "build_stdio_connection",
    "connect_mcp",
    "default_mcp_server_command",
    "get_mcp_tools",
]
