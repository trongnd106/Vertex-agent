"""Phase 2: tool system tests (deepagents 0.7.9).

Covers: custom business tools, the sandboxed code-exec backends (restricted
allowlist + the dev-only LocalShellBackend), role-based tool limiting via
HarnessProfile, and the execute/sandbox matrix from docs/phase-0-discovery.md §4.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from deepagents import HarnessProfile, create_deep_agent, register_harness_profile
from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.protocol import SandboxBackendProtocol
from deepagents.backends.state import StateBackend
from deepagents.profiles.harness.harness_profiles import (
    _get_harness_profile,
    _HARNESS_PROFILES,
)

from src.agent.tools import create_support_ticket, query_order
from src.agent.tools.order_store import list_tickets, reset_store
from src.agent.tools.sandbox import RestrictedShellSandbox
from src.agent import roles

from tests.fake_model import ScriptedChatModel


# --------------------------------------------------------------------------- #
# Shared helpers / fixtures                                                   #
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clean_harness_profiles():
    """Remove any profiles registered during a test so state never leaks."""
    yield
    _HARNESS_PROFILES.clear()


@pytest.fixture(autouse=True)
def _clean_order_store():
    reset_store()
    yield
    reset_store()


class SupportModel(ScriptedChatModel):
    """Fake model that reports a `customer-support` provider so the role
    profile registered under that key is applied by `create_deep_agent`."""

    def _get_ls_params(self, **kwargs):  # multi-provider-safe signature
        return {"ls_provider": "customer-support", "ls_model_name": "fake"}


# --------------------------------------------------------------------------- #
# 1. Custom business tools                                                    #
# --------------------------------------------------------------------------- #
def test_query_order_returns_known_order():
    assert query_order.name == "query_order"
    out = query_order.invoke({"order_id": "A-1001"})
    assert "Ergonomic Keyboard" in out
    assert "shipped" in out
    assert "$89" in out


def test_query_order_unknown_id_error():
    out = query_order.invoke({"order_id": "NOPE"})
    assert "No order found" in out


def test_create_support_ticket_appends_and_returns_id():
    assert create_support_ticket.name == "create_support_ticket"
    ticket_id = create_support_ticket.invoke(
        {"reporter": "alice", "subject": "Battery drains fast", "body": "Phone heats up."}
    )
    assert ticket_id == "T-0001"
    tickets = list_tickets()
    assert len(tickets) == 1
    assert tickets[0]["id"] == ticket_id
    assert tickets[0]["reporter"] == "alice"
    assert tickets[0]["subject"] == "Battery drains fast"
    assert tickets[0]["status"] == "open"


def test_tools_docstrings_are_model_facing():
    # The @tool docstring is the description the model sees; it must not be empty.
    assert query_order.description
    assert create_support_ticket.description


# --------------------------------------------------------------------------- #
# 2. Safe code-exec: RestrictedShellSandbox allowlist                         #
# --------------------------------------------------------------------------- #
def test_restricted_sandbox_is_a_sandbox_protocol():
    assert isinstance(RestrictedShellSandbox(root_dir="/tmp"), SandboxBackendProtocol)
    assert RestrictedShellSandbox(root_dir="/tmp").id


def test_restricted_sandbox_allows_read_only_commands(tmp_path):
    (tmp_path / "a.txt").write_text("hello root", encoding="utf-8")
    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    for cmd in ("pwd", "ls .", "echo hi", "cat a.txt", f"grep -r hello {tmp_path / 'a.txt'}"):
        assert sb.execute(cmd).exit_code == 0, f"should allow: {cmd!r}"


def test_restricted_sandbox_denies_mutation_and_metacharacters():
    sb = RestrictedShellSandbox(root_dir=".")
    for cmd in ("rm -rf /", "mkdir foo", "touch x", "cp a b", "mv a b",
                "ls > out.txt", "ls | grep x", "echo $(id)", "eval echo 1",
                "curl http://x", "python3 -c 'print(1)'"):
        assert sb.execute(cmd).exit_code != 0, f"must reject: {cmd!r}"


def test_restricted_sandbox_downloads_confined_to_root(tmp_path):
    inside = tmp_path / "ok.txt"
    inside.write_text("secret", encoding="utf-8")
    out = tmp_path.parent / "outside.txt"
    out.write_text("x", encoding="utf-8")

    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    ok = sb.download_files([str(inside)])
    assert ok[0].content == b"secret"
    bad = sb.download_files([str(out)])
    assert bad[0].content is None
    assert bad[0].error == "permission_denied"


def test_restricted_sandbox_writes_are_rejected():
    sb = RestrictedShellSandbox(root_dir=".")
    uploads = sb.upload_files([("/x.txt", b"data")])
    assert uploads[0].error == "read_only_sandbox"


# --------------------------------------------------------------------------- #
# 2c. Security regressions (review findings C1/I3)                            #
# --------------------------------------------------------------------------- #
def test_restricted_sandbox_rejects_destructive_find(tmp_path):
    (tmp_path / "doomed.txt").write_text("x", encoding="utf-8")
    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    # `find` is not in the read-only allowlist at all.
    assert sb.execute(f"find {tmp_path} -delete").exit_code != 0
    assert (tmp_path / "doomed.txt").exists(), "find -delete must not delete files"


def test_restricted_sandbox_rejects_sort_output_flag(tmp_path):
    (tmp_path / "a.txt").write_text("b\na\n", encoding="utf-8")
    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    assert sb.execute(f"sort -o {tmp_path / 'sorted.txt'} {tmp_path / 'a.txt'}").exit_code != 0
    assert not (tmp_path / "sorted.txt").exists(), "sort -o must not write a file"
    assert sb.execute(f"sort --output={tmp_path / 'out.txt'} a.txt").exit_code != 0


def test_restricted_sandbox_rejects_path_escape(tmp_path):
    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    # Reading a host path outside the containment root must be rejected.
    for cmd in ("cat /etc/hostname", f"grep -r root /etc/passwd", "ls /"):
        assert sb.execute(cmd).exit_code != 0, f"must reject path escape: {cmd!r}"


def test_restricted_sandbox_rejects_attached_value_path_escape(tmp_path):
    # C1 round-2: an attached short-option value (`-n5`, `-k1`, `-eroot`) must not
    # cause the parser to skip a following file operand in the confinement check.
    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    for cmd in (
        "head -n5 /etc/hostname",
        "tail -n5 /etc/hostname",
        "sort -k1 /etc/hostname",
        "grep -eroot /etc/hostname",
    ):
        assert sb.execute(cmd).exit_code != 0, f"must reject attached-value path escape: {cmd!r}"


def test_restricted_sandbox_attached_value_still_runs_inside_root(tmp_path):
    # The split and attached value forms must still work on confined operands.
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    assert sb.execute("head -n 2 a.txt").exit_code == 0
    assert "line1" in sb.execute("head -n 2 a.txt").output
    assert "line3" in sb.execute("tail -n 1 a.txt").output
    assert "line1" in sb.execute("sort -k1 a.txt").output


def test_restricted_sandbox_applies_default_timeout(tmp_path):
    import os as _os

    fifo = tmp_path / "fifo"
    _os.mkfifo(fifo)
    sb = RestrictedShellSandbox(root_dir=str(tmp_path), default_timeout=1)
    # `cat fifo` blocks on open (no writer), hitting the configured default timeout.
    resp = sb.execute("cat fifo")  # no explicit timeout: backend default applies
    assert resp.exit_code == 124
    assert "timed out" in resp.output


def test_restricted_sandbox_runs_by_argv_not_shell(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    # Command substitution must be inert: the command runs as a literal argv and
    # cannot execute the inner `touch`.
    resp = sb.execute("echo $(touch should_not_exist)")
    assert resp.exit_code != 0
    assert not (tmp_path / "should_not_exist").exists()
    assert not (tmp_path.parent / "should_not_exist").exists()



# --------------------------------------------------------------------------- #
# 2b. DEV path: LocalShellBackend runs a real shell command through the agent #
# --------------------------------------------------------------------------- #
class ExecModel(ScriptedChatModel):
    """Two-turn fake model: calls the built-in `execute` tool, then cites output."""

    def __init__(self, command: str):
        super().__init__()
        self._command = command
        self._turn = 0

    def _next_message(self) -> AIMessage:
        self._turn += 1
        if self._turn == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "execute",
                        "args": {"command": self._command},
                        "id": "call_exec",
                        "type": "tool_call",
                    }
                ],
            )
        for message in reversed(self.last_messages):
            if message.type == "tool":
                return AIMessage(content="OUT:" + str(message.content))
        return AIMessage(content="no tool result")


def test_local_shell_backend_executes_real_command():
    model = ExecModel("echo hello-from-shell")
    agent = create_deep_agent(
        model=model,
        backend=LocalShellBackend(root_dir="."),  # DEV ONLY: unrestricted host shell
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "run"}]})

    assert "execute" in model.bound_tools
    tool_messages = [m for m in result["messages"] if m.type == "tool"]
    assert any("hello-from-shell" in str(m.content) for m in tool_messages)
    last = result["messages"][-1]
    assert last.type == "ai"
    assert "hello-from-shell" in str(last.content)


# --------------------------------------------------------------------------- #
# 2c2. RestrictedShellSandbox wired as a deep-agent backend (review finding I2) #
# --------------------------------------------------------------------------- #
class FsSandboxModel(ScriptedChatModel):
    """Drives ls -> read_file -> write_file through the agent's fs tools."""

    def __init__(self, tmp: "pytest.TempPathFactory"):
        super().__init__()
        self._tmp = tmp
        self._step = 0

    def _next_message(self) -> AIMessage:
        self._step += 1
        if self._step == 1:
            args = {"path": str(self._tmp)}
            name = "ls"
        elif self._step == 2:
            args = {"file_path": str(self._tmp / "a.txt")}
            name = "read_file"
        elif self._step == 3:
            args = {"file_path": str(self._tmp / "should_not_exist.txt"), "content": "x"}
            name = "write_file"
        else:
            for message in reversed(self.last_messages):
                if message.type == "tool":
                    return AIMessage(content="DONE:" + str(message.content)[:200])
            return AIMessage(content="no tool result")
        return AIMessage(
            content="",
            tool_calls=[
                {"name": name, "args": args, "id": f"call_{self._step}", "type": "tool_call"}
            ],
        )


def test_restricted_sandbox_fs_helpers_real_and_writes_denied(tmp_path):
    (tmp_path / "a.txt").write_text("unique-marker-123\n", encoding="utf-8")
    model = FsSandboxModel(tmp_path)
    agent = create_deep_agent(
        model=model,
        backend=RestrictedShellSandbox(root_dir=str(tmp_path)),
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "inspect"}]})

    # ls must return the real file, not an empty list.
    assert any("a.txt" in str(m.content) for m in result["messages"])
    # read_file must return the real contents, not a hard error / empty.
    assert any("unique-marker-123" in str(m.content) for m in result["messages"])
    # write_file must be denied (read-only), and no silent success / no file.
    wm = [m for m in result["messages"] if m.type == "tool" and m.name == "write_file"]
    assert wm, "expected a write_file tool message"
    assert wm[0].status == "error" or "read_only" in str(wm[0].content).lower()
    assert not (tmp_path / "should_not_exist.txt").exists()


def test_restricted_sandbox_native_read_respects_pagination(tmp_path):
    from deepagents.backends.protocol import ReadResult

    text = "".join(f"line{i}\n" for i in range(10))
    (tmp_path / "f.txt").write_text(text, encoding="utf-8")
    sb = RestrictedShellSandbox(root_dir=str(tmp_path))
    r: ReadResult = sb.read(str(tmp_path / "f.txt"), offset=2, limit=3)
    assert r.error is None
    assert "line2" in r.file_data["content"]
    assert r.file_data["content"].startswith("line2\n")
    assert r.start_line == 3
    assert r.end_line == 5
    assert r.next_offset == 5



# --------------------------------------------------------------------------- #
# 3. HarnessProfile role-based tool limiting                                  #
# --------------------------------------------------------------------------- #
def test_customer_support_role_excludes_execute():
    roles.register_customer_support_role()
    profile = _get_harness_profile(roles.CUSTOMER_SUPPORT_ROLE)
    assert profile is not None
    assert "execute" in profile.excluded_tools


def test_operator_role_keeps_all_tools():
    roles.register_operator_role()
    profile = _get_harness_profile(roles.OPERATOR_ROLE)
    assert profile is not None
    assert profile.excluded_tools == frozenset()


def test_customer_support_role_exclusion_applies_to_agent():
    roles.register_customer_support_role()
    model = SupportModel()
    agent = create_deep_agent(model=model)
    agent.invoke({"messages": [{"role": "user", "content": "hi"}]})

    assert "execute" not in model.bound_tools
    for builtin in ("ls", "read_file", "write_file", "edit_file", "glob", "grep", "task"):
        assert builtin in model.bound_tools, f"expected built-in {builtin!r} to remain"


def test_registration_is_idempotent():
    roles.register_customer_support_role()
    first = _get_harness_profile(roles.CUSTOMER_SUPPORT_ROLE).excluded_tools
    roles.register_customer_support_role()
    second = _get_harness_profile(roles.CUSTOMER_SUPPORT_ROLE).excluded_tools
    assert second == first == frozenset({"execute"})


def test_registration_is_additive_union():
    roles.register_customer_support_role()
    register_harness_profile(
        roles.CUSTOMER_SUPPORT_ROLE,
        HarnessProfile(excluded_tools=frozenset({"grep"})),
    )
    profile = _get_harness_profile(roles.CUSTOMER_SUPPORT_ROLE)
    assert profile.excluded_tools == frozenset({"execute", "grep"})


# --------------------------------------------------------------------------- #
# 4. Execute/sandbox matrix regression guard (discovery doc §4)               #
# --------------------------------------------------------------------------- #
def test_state_backend_does_not_satisfy_sandbox_protocol():
    assert not isinstance(StateBackend(), SandboxBackendProtocol)


def test_local_shell_backend_satisfies_sandbox_protocol():
    assert isinstance(LocalShellBackend(), SandboxBackendProtocol)
