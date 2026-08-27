"""Phase 2: MCP integration tests (deepagents 0.7.9 + langchain-mcp-adapters 0.3.2).

Exercises the in-repo stdio MCP fixture (`tests/fixtures/mcp_server.py`) through
`MultiServerMCPClient` (ruling M5: no external MCP service), and proves the
resulting LangChain tools flow into a deep agent and are callable by a fake
model via `ainvoke`.

API facts (recorded in docs/phase-0-discovery.md §12):

- `MultiServerMCPClient` stdio connection is a dict `{server: {transport:
  "stdio", command, args}}`; it is NOT an async context manager in 0.3.2.
- MCP tools are async-only `StructuredTool`s, so agent turns that call them must
  use `ainvoke` (sync `invoke` raises "StructuredTool does not support sync
  invocation").
- With `tool_name_prefix=True` the tool name becomes `f"{server_name}_{tool}"`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from langchain_core.messages import AIMessage
from deepagents import create_deep_agent

from src.agent.mcp.mcp_client import (
    DEFAULT_SERVER_NAME,
    build_stdio_connection,
    connect_mcp,
    default_mcp_server_command,
    get_mcp_tools,
)

from tests.fake_model import ScriptedChatModel

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mcp_server.py"


def _await(coro):
    """Run a coroutine to completion inside a fresh event loop."""
    return asyncio.run(coro)


class McpCallerModel(ScriptedChatModel):
    """Two-turn fake model: calls the namespaced MCP tool, then cites its output."""

    def __init__(self, tool_name: str, tool_args: dict):
        super().__init__()
        self._tool_name = tool_name
        self._tool_args = tool_args
        self._turn = 0

    def _next_message(self) -> AIMessage:
        self._turn += 1
        if self._turn == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": self._tool_name,
                        "args": self._tool_args,
                        "id": "call_mcp_1",
                        "type": "tool_call",
                    }
                ],
            )
        for message in reversed(self.last_messages):
            if message.type == "tool":
                return AIMessage(content="OUT:" + str(message.content))
        return AIMessage(content="no tool result")


# --------------------------------------------------------------------------- #
# Client + fixture server                                                     #
# --------------------------------------------------------------------------- #
def test_fixture_server_path_points_at_real_file():
    assert FIXTURE.exists()
    command = default_mcp_server_command()
    assert command[0].endswith("python")
    assert command[1].endswith("mcp_server.py")


def test_default_connection_is_stdio_to_fixture():
    conn = build_stdio_connection()
    spec = conn[DEFAULT_SERVER_NAME]
    assert spec["transport"] == "stdio"
    assert spec["command"].endswith("python")
    assert spec["args"][0].endswith("mcp_server.py")


def test_get_tools_exposes_prefixed_mcp_tools():
    tools = _await(_get_tools_prefixed())
    names = sorted(t.name for t in tools)
    assert names == ["fixture-mcp_echo", "fixture-mcp_get_weather"]


async def _get_tools_prefixed():
    client = connect_mcp(tool_name_prefix=True)
    return await get_mcp_tools(client)


# --------------------------------------------------------------------------- #
# Tools flow into the deep agent                                              #
# --------------------------------------------------------------------------- #
def test_mcp_tools_exposed_in_deep_agent_with_namespace():
    async def scene():
        client = connect_mcp(tool_name_prefix=True)
        tools = await get_mcp_tools(client)
        model = ScriptedChatModel()
        agent = create_deep_agent(model=model, tools=tools)
        await agent.ainvoke({"messages": [{"role": "user", "content": "hi"}]})
        return model

    model = _await(scene())
    assert "fixture-mcp_get_weather" in model.bound_tools
    assert "fixture-mcp_echo" in model.bound_tools


def test_fake_model_turn_calling_mcp_tool_returns_result():
    async def scene():
        client = connect_mcp(tool_name_prefix=True)
        tools = await get_mcp_tools(client)
        model = McpCallerModel(
            "fixture-mcp_get_weather",
            {"city": "Hanoi"},
        )
        agent = create_deep_agent(model=model, tools=tools)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": "weather in Hanoi"}]}
        )
        return model, result

    model, result = _await(scene())

    assert "fixture-mcp_get_weather" in model.bound_tools
    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert any("24°C" in str(m.content) for m in tool_messages)

    last = result["messages"][-1]
    assert last.type == "ai"
    assert "24°C" in str(last.content)
