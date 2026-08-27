"""A genuine, minimal MCP server used as a test fixture.

Runs over the stdio transport (the default for `mcp.server.fastmcp.FastMCP`).
It announces two tools and handles their calls, so tests can exercise the
in-repo MCP path end-to-end through `MultiServerMCPClient` (no network, no
remote service — per ruling M5).

Run standalone for a quick sanity check::

    .venv/bin/python tests/fixtures/mcp_server.py
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

WEATHER = {
    "Hanoi": "24°C, partly cloudy",
    "Paris": "18°C, light rain",
    "Tokyo": "22°C, clear",
}


def create_server() -> FastMCP:
    """Build and return the FastMCP server with its tools."""
    mcp = FastMCP("fixture-mcp")

    @mcp.tool()
    def get_weather(city: str) -> str:
        """Return a deterministic weather report for a known city."""
        return WEATHER.get(city, f"No data for city '{city}'.")

    @mcp.tool()
    def echo(text: str) -> str:
        """Echo back the exact text that was passed in."""
        return text

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
