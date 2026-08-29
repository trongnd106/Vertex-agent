"""Phase 7: filesystem permission boundary tests (deepagents 0.7.9).

Verifies `permissions=[FilesystemPermission(...)]` in `create_deep_agent`:

- `mode="deny"` turns a matching tool call into a permission-denied
  `ToolMessage` (status="error") and filters denied entries out of bulk
  listings (`ls`) instead of running the operation.
- `mode="interrupt"` pauses the graph for human approval: `invoke` returns a
  state carrying `__interrupt__` (an `Interrupt` whose value holds the
  `HITLRequest` action/review configs) and the tool never executes.
- Honest-scope guard: filesystem permissions gate ONLY the built-in
  filesystem middleware tools — they do NOT gate the sandboxed `execute` tool
  from Task 2.

Runbook reference: `docs/runbook-observability.md`; source citations in
`docs/phase-0-discovery.md` §16.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware._fs_interrupt import _build_interrupt_on_from_permissions

from tests.fake_model import ScriptedChatModel


def _read_tool_call(tool_call_id: str, file_path: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read_file",
                "args": {"file_path": file_path},
                "id": tool_call_id,
                "type": "tool_call",
            }
        ],
    )


def _write_tool_call(tool_call_id: str, file_path: str, content: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "write_file",
                "args": {"file_path": file_path, "content": content},
                "id": tool_call_id,
                "type": "tool_call",
            }
        ],
    )


def _ls_tool_call(tool_call_id: str, path: str = ".") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "ls",
                "args": {"path": path},
                "id": tool_call_id,
                "type": "tool_call",
            }
        ],
    )


class ToolScriptModel(ScriptedChatModel):
    """Replays a scripted FIFO of tool-call AIMessages, then summarises results."""

    def _next_message(self) -> AIMessage:
        if self._script:
            return self._script.pop(0)
        for message in reversed(self.last_messages):
            if message.type == "tool":
                return AIMessage(content="DONE:" + str(message.content)[:200])
        return AIMessage(content="no tool result")


# --------------------------------------------------------------------------- #
# 1. FilesystemPermission shape / validation (the fields the brief asked to map) #
# --------------------------------------------------------------------------- #
def test_permission_fields_model_and_default() -> None:
    p = FilesystemPermission(operations=["read"], paths=["/secrets/**"])
    assert p.operations == ["read"]
    assert p.paths == ["/secrets/**"]
    assert p.mode == "allow", "mode must default to 'allow'"


def test_permission_mode_accepts_each_literal() -> None:
    for mode in ("allow", "deny", "interrupt"):
        permission = FilesystemPermission(
            operations=["read"],
            paths=["/x"],
            mode=mode,  # type: ignore[arg-type]
        )
        assert permission.mode == mode


def test_permission_path_validation() -> None:
    # Paths must be absolute, must not contain '..', and must not contain '~'.
    with pytest.raises(ValueError):
        FilesystemPermission(operations=["read"], paths=["relative/path"])
    with pytest.raises(ValueError):
        FilesystemPermission(operations=["read"], paths=["/a/../b"])
    with pytest.raises(NotImplementedError):
        FilesystemPermission(operations=["read"], paths=["/~/home"])


# --------------------------------------------------------------------------- #
# 2. mode="deny" — a read-only call toward a restricted path is denied         #
# --------------------------------------------------------------------------- #
def test_deny_read_file_returns_error_and_never_leaks(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("TOP-SECRET-MARKER-xyz", encoding="utf-8")

    model = ToolScriptModel(script=[_read_tool_call("c1", "/secret.txt")])
    agent = create_deep_agent(
        model=model,
        backend=FilesystemBackend(root_dir=str(tmp_path)),
        permissions=[
            FilesystemPermission(
                operations=["read"], paths=["/secret.txt"], mode="deny"
            )
        ],
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "read it"}]})

    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert tool_messages, "expected a read_file ToolMessage"
    assert tool_messages[0].status == "error"
    assert "permission denied" in str(tool_messages[0].content).lower()
    assert all(
        "TOP-SECRET-MARKER-xyz" not in str(m.content) for m in result["messages"]
    )


def test_deny_allows_read_of_non_restricted_path(tmp_path: Path) -> None:
    (tmp_path / "plain.txt").write_text("public-content", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP-SECRET-MARKER-xyz", encoding="utf-8")

    def read_script(path: str) -> list[AIMessage]:
        return [_read_tool_call("c1", path)]

    # A read of the denied path errors and never returns contents.
    denied = ToolScriptModel(script=read_script("/secret.txt"))
    agent = create_deep_agent(
        model=denied,
        backend=FilesystemBackend(root_dir=str(tmp_path)),
        permissions=[
            FilesystemPermission(
                operations=["read"], paths=["/secret.txt"], mode="deny"
            )
        ],
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "read"}]})
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert tool_msgs[0].status == "error"
    assert "TOP-SECRET-MARKER-xyz" not in str(result["messages"])

    # A sibling path outside the denied rule still works.
    allowed = ToolScriptModel(script=read_script("/plain.txt"))
    agent2 = create_deep_agent(
        model=allowed,
        backend=FilesystemBackend(root_dir=str(tmp_path)),
        permissions=[
            FilesystemPermission(
                operations=["read"], paths=["/secret.txt"], mode="deny"
            )
        ],
    )
    result2 = agent2.invoke({"messages": [{"role": "user", "content": "read"}]})
    assert any("public-content" in str(m.content) for m in result2["messages"])


def test_deny_write_prevents_file_creation_inside_protected_subtree(
    tmp_path: Path,
) -> None:
    model = ToolScriptModel(
        script=[_write_tool_call("c1", "/protected/x.txt", "evil")]
    )
    agent = create_deep_agent(
        model=model,
        backend=FilesystemBackend(root_dir=str(tmp_path)),
        permissions=[
            FilesystemPermission(
                operations=["write"], paths=["/protected/**"], mode="deny"
            )
        ],
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "write"}]})

    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert tool_messages[0].status == "error"
    assert "permission denied" in str(tool_messages[0].content).lower()
    assert not (tmp_path / "protected" / "x.txt").exists(), (
        "denied write must not create a file"
    )


def test_deny_filters_bulk_listing_but_keeps_other_entries(tmp_path: Path) -> None:
    (tmp_path / "plain.txt").write_text("p", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("S", encoding="utf-8")

    model = ToolScriptModel(script=[_ls_tool_call("c1", ".")])
    agent = create_deep_agent(
        model=model,
        backend=FilesystemBackend(root_dir=str(tmp_path)),
        permissions=[
            FilesystemPermission(
                operations=["read"], paths=["/secret.txt"], mode="deny"
            )
        ],
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "list"}]})

    listing = [str(m.content) for m in result["messages"] if m.type == "tool"][0]
    assert "/plain.txt" in listing
    assert "secret.txt" not in listing, "denied path must be filtered out of ls results"


# --------------------------------------------------------------------------- #
# 3. mode="interrupt" — paused for approval instead of silently running        #
# --------------------------------------------------------------------------- #
def test_interrupt_pauses_graph_for_approval_and_does_not_run_tool(
    tmp_path: Path,
) -> None:
    (tmp_path / "secret.txt").write_text("TOP-SECRET-MARKER-xyz", encoding="utf-8")

    model = ToolScriptModel(script=[_read_tool_call("c1", "/secret.txt")])
    agent = create_deep_agent(
        model=model,
        backend=FilesystemBackend(root_dir=str(tmp_path)),
        permissions=[
            FilesystemPermission(
                operations=["read"], paths=["/secret.txt"], mode="interrupt"
            )
        ],
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "read"}]})

    interrupts = result.get("__interrupt__")
    assert interrupts, "interrupt-mode call must pause the graph"
    hitl = interrupts[0].value
    assert isinstance(hitl, dict)
    assert "action_requests" in hitl, "interrupt must carry the HITL action requests"
    # The tool must not have executed: no read_file ToolMessage, no content.
    assert not [m for m in result["messages"] if m.type == "tool"], "tool must not run"
    assert all(
        "TOP-SECRET-MARKER-xyz" not in str(m.content) for m in result["messages"]
    )


# --------------------------------------------------------------------------- #
# 4. Honest scope: FilesystemPermission does NOT gate the sandboxed execute    #
# --------------------------------------------------------------------------- #
def test_permissions_interrupt_mapping_never_gates_execute() -> None:
    rules = [
        FilesystemPermission(
            operations=["read", "write"], paths=["/**"], mode="interrupt"
        )
    ]
    interrupt_on = _build_interrupt_on_from_permissions(rules)
    assert set(interrupt_on) == {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
    }
    assert "execute" not in interrupt_on
    assert "task" not in interrupt_on