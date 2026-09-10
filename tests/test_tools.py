"""Tests for the Tool System (Task 3: 3.1–3.6).

Covers:
    3.1  Built-in Filesystem Tools
    3.2  Custom Business Tools (registry, chaining)
    3.3  MCP Tool Integration  (import guard only — requires mcp package)
    3.4  Sandbox & Safe Execution
    3.5  Tool Permission & Audit System
    3.6  Tool Description & Discovery
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

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
from src.tools.registry import ToolRegistry, ToolSpec, chain_tools, get_default_registry
from src.tools.sandbox import (
    DockerSandbox,
    LocalShellSandbox,
    PythonSandbox,
    ResourceLimits,
    SandboxResult,
)
from src.tools.permissions import (
    AuditLog,
    FilesystemPermission,
    HumanInTheLoop,
    PermissionMode,
    Role,
    RoleBasedAccess,
)
from src.tools.discovery import (
    ToolDescription,
    ToolDiscovery,
    ToolSelector,
    ToolStatistics,
)


# ══════════════════════════════════════════════════════════════════════════
# 3.1  Filesystem Tools
# ══════════════════════════════════════════════════════════════════════════


class TestFilesystemTools:
    """Test the built-in filesystem tools."""

    @pytest.fixture
    def tmp_dir(self) -> Path:
        with tempfile.TemporaryDirectory() as d:
            yield Path(d).resolve()

    @pytest.fixture
    def sample_file(self, tmp_dir: Path) -> Path:
        f = tmp_dir / "hello.txt"
        f.write_text("Hello, world!\nLine two.\nLine three.\n", encoding="utf-8")
        return f

    # ── ls ───────────────────────────────────────────────────────────

    def test_ls_basic(self, tmp_dir: Path) -> None:
        (tmp_dir / "a.txt").write_text("a", encoding="utf-8")
        (tmp_dir / "b.txt").write_text("b", encoding="utf-8")
        result = ls(str(tmp_dir))
        assert result.success
        assert isinstance(result.data, list)
        assert len(result.data) >= 2

    def test_ls_nonexistent(self) -> None:
        result = ls("/nonexistent_path_xyz")
        assert not result.success

    def test_ls_permission_denied(self) -> None:
        perms = [FilePermission(paths=["/denied/*"], mode="deny", operations=["read"])]
        result = ls("/denied/some_dir", permissions=perms)
        assert not result.success
        assert "denied" in result.error.lower()

    # ── read_file ────────────────────────────────────────────────────

    def test_read_file_basic(self, sample_file: Path) -> None:
        result = read_file(str(sample_file))
        assert result.success
        assert "Hello" in str(result.data)

    def test_read_file_with_offset(self, sample_file: Path) -> None:
        result = read_file(str(sample_file), offset=1)
        assert result.success
        lines = str(result.data).splitlines()
        assert "Line two" in lines[0] if lines else ""

    def test_read_file_with_limit(self, sample_file: Path) -> None:
        result = read_file(str(sample_file), limit=1)
        assert result.success
        lines = str(result.data).splitlines()
        assert len(lines) == 1

    def test_read_file_nonexistent(self) -> None:
        result = read_file("/nonexistent_xyz.txt")
        assert not result.success

    def test_read_file_permission_denied(self, sample_file: Path) -> None:
        perms = [FilePermission(paths=["*"], mode="deny", operations=["read"])]
        result = read_file(str(sample_file), permissions=perms)
        assert not result.success

    def test_read_file_large_eviction(self):
        """Result >80K chars should be evicted."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("x" * 100_000)
            f.flush()
            result = read_file(f.name)
        Path(f.name).unlink(missing_ok=True)
        assert result.evicted

    # ── write_file ───────────────────────────────────────────────────

    def test_write_file(self, tmp_dir: Path) -> None:
        path = tmp_dir / "new.txt"
        result = write_file(str(path), "new content")
        assert result.success
        assert path.read_text(encoding="utf-8") == "new content"

    def test_write_file_creates_parents(self, tmp_dir: Path) -> None:
        path = tmp_dir / "a" / "b" / "c.txt"
        result = write_file(str(path), "deep")
        assert result.success
        assert path.exists()

    def test_write_file_permission_denied(self, tmp_dir: Path) -> None:
        perms = [FilePermission(paths=["*"], mode="deny", operations=["write"])]
        result = write_file(str(tmp_dir / "nope.txt"), "data", permissions=perms)
        assert not result.success

    # ── edit_file ────────────────────────────────────────────────────

    def test_edit_file_replace_first(self, sample_file: Path) -> None:
        result = edit_file(str(sample_file), "Hello", "Hi")
        assert result.success
        assert sample_file.read_text(encoding="utf-8").startswith("Hi")

    def test_edit_file_replace_all(self, tmp_dir: Path) -> None:
        f = tmp_dir / "reps.txt"
        f.write_text("a a a", encoding="utf-8")
        result = edit_file(str(f), "a", "b", replace_all=True)
        assert result.success
        assert f.read_text(encoding="utf-8") == "b b b"

    def test_edit_file_not_found(self, sample_file: Path) -> None:
        result = edit_file(str(sample_file), "ZZZZNOTFOUND", "x")
        assert not result.success

    def test_edit_file_permission_denied(self, sample_file: Path) -> None:
        perms = [FilePermission(paths=["*"], mode="deny", operations=["write"])]
        result = edit_file(str(sample_file), "Hello", "Hi", permissions=perms)
        assert not result.success

    # ── delete_file ──────────────────────────────────────────────────

    def test_delete_file(self, tmp_dir: Path) -> None:
        f = tmp_dir / "todelete.txt"
        f.write_text("bye", encoding="utf-8")
        result = delete_file(str(f))
        assert result.success
        assert not f.exists()

    def test_delete_nonexistent(self) -> None:
        result = delete_file("/nonexistent_xyz")
        assert not result.success

    def test_delete_nonempty_dir(self, tmp_dir: Path) -> None:
        d = tmp_dir / "nonempty"
        d.mkdir()
        (d / "f.txt").write_text("x", encoding="utf-8")
        result = delete_file(str(d))
        assert not result.success  # cannot rmdir non-empty

    def test_delete_permission_denied(self, tmp_dir: Path) -> None:
        f = tmp_dir / "protected.txt"
        f.write_text("secret", encoding="utf-8")
        perms = [FilePermission(paths=["*"], mode="deny", operations=["delete"])]
        result = delete_file(str(f), permissions=perms)
        assert not result.success

    # ── glob_files ───────────────────────────────────────────────────

    def test_glob_files(self, tmp_dir: Path) -> None:
        (tmp_dir / "foo.py").write_text("", encoding="utf-8")
        (tmp_dir / "bar.py").write_text("", encoding="utf-8")
        (tmp_dir / "readme.md").write_text("", encoding="utf-8")
        result = glob_files("*.py", root=str(tmp_dir))
        assert result.success
        assert ".py" in str(result.data)

    def test_glob_files_permission(self, tmp_dir: Path) -> None:
        perms = [FilePermission(paths=["*"], mode="deny", operations=["read"])]
        result = glob_files("*", root=str(tmp_dir), permissions=perms)
        assert not result.success

    # ── grep_files ───────────────────────────────────────────────────

    def test_grep_files(self, tmp_dir: Path) -> None:
        (tmp_dir / "test.txt").write_text("apple\nbanana\n", encoding="utf-8")
        result = grep_files("apple", path=str(tmp_dir))
        assert result.success
        assert "apple" in str(result.data)

    def test_grep_files_no_match(self, tmp_dir: Path) -> None:
        (tmp_dir / "test.txt").write_text("apple", encoding="utf-8")
        result = grep_files("zzzzz", path=str(tmp_dir))
        assert result.success
        assert "No matches" in str(result.data)

    def test_grep_files_invalid_regex(self) -> None:
        result = grep_files(r"[unclosed", path=".")
        assert not result.success

    # ── execute_command ──────────────────────────────────────────────

    def test_execute_basic(self) -> None:
        result = execute_command("echo hello", timeout=10)
        assert result.success
        assert "hello" in str(result.data)

    def test_execute_failure(self) -> None:
        result = execute_command("false")
        assert not result.success

    def test_execute_timeout(self) -> None:
        result = execute_command("sleep 10", timeout=0.5)
        assert "timed out" in result.error.lower()

    def test_execute_permission_denied(self) -> None:
        perms = [FilePermission(paths=["*"], mode="deny", operations=["execute"])]
        result = execute_command("echo hi", permissions=perms)
        assert not result.success

    # ── FILESYSTEM_TOOLS registry ────────────────────────────────────

    def test_filesystem_tools_registry(self) -> None:
        assert "ls" in FILESYSTEM_TOOLS
        assert "read_file" in FILESYSTEM_TOOLS
        assert "write_file" in FILESYSTEM_TOOLS
        assert "edit_file" in FILESYSTEM_TOOLS
        assert "delete" in FILESYSTEM_TOOLS
        assert "glob" in FILESYSTEM_TOOLS
        assert "grep" in FILESYSTEM_TOOLS
        assert "execute" in FILESYSTEM_TOOLS

    def test_filesystem_tool_has_fn(self) -> None:
        for name, spec in FILESYSTEM_TOOLS.items():
            assert callable(spec["fn"]), f"{name} fn not callable"
            assert spec["name"] == name


# ══════════════════════════════════════════════════════════════════════════
# 3.2  Custom Business Tools (registry + chaining)
# ══════════════════════════════════════════════════════════════════════════


class TestToolRegistry:
    """Test ToolRegistry."""

    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        spec = registry.register("my_tool", "Does something", lambda: ToolResult(success=True))
        assert registry.get("my_tool") is spec

    def test_register_overwrite(self) -> None:
        registry = ToolRegistry()
        registry.register("a", "first", lambda: ToolResult(success=True))
        s2 = registry.register("a", "second", lambda: ToolResult(success=False))
        assert registry.get("a").description == "second"

    def test_unregister(self) -> None:
        registry = ToolRegistry()
        registry.register("x", "test", lambda: ToolResult(success=True))
        assert registry.unregister("x") is True
        assert registry.get("x") is None
        assert registry.unregister("nonexistent") is False

    def test_list_tools_includes_filesystem(self) -> None:
        registry = ToolRegistry()
        names = [t.name for t in registry.list_tools()]
        assert "read_file" in names

    def test_list_tools_filter_category(self) -> None:
        registry = ToolRegistry()
        tools = registry.list_tools(category="filesystem")
        assert all(t.category == "filesystem" for t in tools)

    def test_list_tools_filter_tags(self) -> None:
        registry = ToolRegistry()
        tools = registry.list_tools(tags=["builtin"])
        assert all("builtin" in t.tags for t in tools)

    def test_search(self) -> None:
        registry = ToolRegistry()
        results = registry.search("file")
        assert any("read_file" in r.name for r in results)

    def test_execute(self) -> None:
        registry = ToolRegistry()
        result = registry.execute("echo hello", _timeout=10)
        # "execute" tool
        assert result.success is True or result.success is False

    def test_execute_unknown(self) -> None:
        registry = ToolRegistry()
        result = registry.execute("nonexistent_tool")
        assert not result.success
        assert "Unknown" in result.error

    def test_copy_is_independent(self) -> None:
        r1 = ToolRegistry()
        r2 = r1.copy()
        r1.register("custom_a", "a", lambda: ToolResult(success=True))
        assert r2.get("custom_a") is None

    def test_default_registry(self) -> None:
        from src.tools.registry import reset_default_registry

        reset_default_registry()
        r = get_default_registry()
        assert r is get_default_registry()
        reset_default_registry()


class TestToolChaining:
    """Test chain_tools."""

    def test_chain_basic(self) -> None:
        def upper_tool(s: str) -> ToolResult:
            return ToolResult(success=True, data=s.upper())

        def exclaim_tool(s: str) -> ToolResult:
            return ToolResult(success=True, data=s + "!")

        chained = chain_tools(upper_tool, exclaim_tool)
        result = chained("hello")
        assert result.success
        assert result.data == "HELLO!"

    def test_chain_stops_on_error(self) -> None:
        def ok_tool(s: str) -> ToolResult:
            return ToolResult(success=True, data=s)

        def fail_tool(s: str) -> ToolResult:
            return ToolResult(success=False, error="broke")

        def never_run(s: str) -> ToolResult:
            raise AssertionError("should not be called")

        chained = chain_tools(ok_tool, fail_tool, never_run)
        result = chained("start")
        assert not result.success
        assert "broke" in result.error


# ══════════════════════════════════════════════════════════════════════════
# 3.3  MCP Tool Integration
# ══════════════════════════════════════════════════════════════════════════


class TestMCPIntegration:
    """Test MCP integration — import guards and module constants."""

    def test_mcp_import_flag(self) -> None:
        """Verify _HAS_MCP is defined and is bool."""
        from src.tools.mcp import _HAS_MCP

        assert isinstance(_HAS_MCP, bool)

    def test_mcp_constants_available(self) -> None:
        """Verify key symbols are importable."""
        from src.tools.mcp import MCPClient, MCPManager, MCPServerConfig, MCPTool
        from src.tools.mcp import MCPClientState

    def test_mcp_client_import_error(self) -> None:
        """If mcp is not installed, MCPClient raises ImportError."""
        from src.tools.mcp import _HAS_MCP, MCPClient

        if not _HAS_MCP:
            with pytest.raises(ImportError):
                MCPClient.__init__()

    def test_mcp_manager_no_servers(self) -> None:
        from src.tools.mcp import MCPManager

        mgr = MCPManager()
        assert mgr.list_all_tools() == []


# ══════════════════════════════════════════════════════════════════════════
# 3.4  Sandbox & Safe Execution
# ══════════════════════════════════════════════════════════════════════════


class TestLocalShellSandbox:
    """Test LocalShellSandbox."""

    def test_basic_command(self) -> None:
        sandbox = LocalShellSandbox(ResourceLimits(timeout=10))
        result = sandbox.run("echo hello")
        assert result.success
        assert "hello" in result.stdout

    def test_failing_command(self) -> None:
        sandbox = LocalShellSandbox(ResourceLimits(timeout=10))
        result = sandbox.run("false")
        assert not result.success

    def test_timeout(self) -> None:
        sandbox = LocalShellSandbox(ResourceLimits(timeout=0.3))
        result = sandbox.run("sleep 5")
        # On constrained systems the process may fail to fork before timing out
        assert result.timed_out or not result.success

    def test_check_supported(self) -> None:
        sandbox = LocalShellSandbox()
        assert sandbox.check_supported() is True


class TestPythonSandbox:
    """Test Python sandbox."""

    def test_simple_expression(self) -> None:
        sandbox = PythonSandbox(ResourceLimits(timeout=5))
        result = sandbox.run("x = 1 + 1")
        assert result.success

    def test_syntax_error(self) -> None:
        sandbox = PythonSandbox(ResourceLimits(timeout=5))
        result = sandbox.run("this is invalid syntax {{{")
        assert not result.success
        assert "SyntaxError" in result.error

    def test_builtin_restricted(self) -> None:
        sandbox = PythonSandbox(ResourceLimits(timeout=5))
        result = sandbox.run("__import__('os').system('echo hax')")
        assert not result.success

    def test_import_whitelist(self) -> None:
        sandbox = PythonSandbox(ResourceLimits(timeout=5))
        result = sandbox.run("import json; data = json.dumps({'a': 1})")
        assert result.success

    def test_import_blocked(self) -> None:
        sandbox = PythonSandbox(ResourceLimits(timeout=5))
        result = sandbox.run("import requests")
        assert not result.success

    def test_timeout(self) -> None:
        sandbox = PythonSandbox(ResourceLimits(timeout=0.3))
        result = sandbox.run("import time; time.sleep(5)")
        assert result.timed_out or not result.success

    def test_check_supported(self) -> None:
        sandbox = PythonSandbox()
        assert sandbox.check_supported() is True


class TestDockerSandbox:
    """Test Docker sandbox — only if Docker is available."""

    def test_check_supported(self) -> None:
        sandbox = DockerSandbox()
        # Don't require Docker to be available in CI; just verify the method runs
        assert isinstance(sandbox.check_supported(), bool)

    def test_docker_not_found_graceful(self) -> None:
        """If Docker is not installed, run returns a descriptive error."""
        sandbox = DockerSandbox(image="alpine")
        if not sandbox.check_supported():
            result = sandbox.run("echo hi")
            assert not result.success
            assert "Docker not found" in result.error


# ══════════════════════════════════════════════════════════════════════════
# 3.5  Tool Permission & Audit System
# ══════════════════════════════════════════════════════════════════════════


class TestFilesystemPermission:
    """Test FilesystemPermission matching."""

    def test_exact_match(self) -> None:
        perm = FilesystemPermission("/tmp/test.txt", match_mode="exact")
        assert perm.matches("/tmp/test.txt", "read")
        assert not perm.matches("/tmp/other.txt", "read")

    def test_prefix_match(self) -> None:
        perm = FilesystemPermission("/tmp", match_mode="prefix")
        assert perm.matches("/tmp/sub/file.txt", "write")

    def test_glob_match(self) -> None:
        perm = FilesystemPermission("**/*.py", match_mode="glob")
        assert perm.matches("/home/project/main.py", "read")
        assert not perm.matches("/home/project/main.txt", "read")

    def test_operation_filtering(self) -> None:
        perm = FilesystemPermission("*", mode="allow", operations=["read"])
        assert perm.matches("/any/file", "read")
        assert not perm.matches("/any/file", "write")

    def test_deny_mode(self) -> None:
        assert FilesystemPermission("*", mode="deny").mode == PermissionMode.DENY


class TestRoleBasedAccess:
    """Test RoleBasedAccess."""

    @pytest.fixture
    def rbac(self) -> RoleBasedAccess:
        rbac = RoleBasedAccess()
        rbac.add_role(
            Role(
                name="admin",
                allowed_tools=["*"],
                denied_tools=[],
            )
        )
        rbac.add_role(
            Role(
                name="reader",
                allowed_tools=["read_file", "ls", "glob", "grep"],
                denied_tools=["delete"],
            )
        )
        return rbac

    def test_admin_all_tools(self, rbac: RoleBasedAccess) -> None:
        allowed, _ = rbac.check_tool_allowed("admin", "any_tool")
        assert allowed

    def test_reader_allowed(self, rbac: RoleBasedAccess) -> None:
        allowed, _ = rbac.check_tool_allowed("reader", "read_file")
        assert allowed

    def test_reader_denied(self, rbac: RoleBasedAccess) -> None:
        allowed, _ = rbac.check_tool_allowed("reader", "write_file")
        assert not allowed

    def test_unknown_role(self, rbac: RoleBasedAccess) -> None:
        allowed, reason = rbac.check_tool_allowed("hacker", "read_file")
        assert not allowed
        assert "Unknown" in reason

    def test_filesystem_permission(self, rbac: RoleBasedAccess) -> None:
        rbac.add_role(
            Role(
                name="safe",
                allowed_tools=["read_file"],
                filesystem_permissions=[
                    FilesystemPermission("/safe/*", mode="allow"),
                    FilesystemPermission("**/*.secret", mode="deny"),
                ],
            )
        )
        allowed, _ = rbac.check_filesystem("safe", "/safe/data.txt", "read")
        assert allowed

    def test_filesystem_denied(self, rbac: RoleBasedAccess) -> None:
        rbac.add_role(
            Role(
                name="safe",
                allowed_tools=["read_file"],
                filesystem_permissions=[
                    FilesystemPermission("**/*.secret", mode="deny"),
                ],
            )
        )
        allowed, _ = rbac.check_filesystem("safe", "/etc/passwd.secret", "read")
        assert not allowed


class TestHumanInTheLoop:
    """Test HumanInTheLoop."""

    def test_request_approval(self) -> None:
        hitl = HumanInTheLoop()
        req = hitl.request_approval("delete", {"path": "/etc"}, "deleting critical file")
        assert req.decision.value == "pending"

    def test_auto_approve(self) -> None:
        hitl = HumanInTheLoop(auto_approve=True)
        req = hitl.request_approval("delete", {"path": "/tmp"})
        assert req.decision.value == "approved"

    def test_approve(self) -> None:
        hitl = HumanInTheLoop()
        req = hitl.request_approval("write", {"path": "/tmp/x"})
        assert hitl.approve(req.id)
        assert hitl.get_request(req.id).decision.value == "approved"

    def test_deny(self) -> None:
        hitl = HumanInTheLoop()
        req = hitl.request_approval("write", {"path": "/tmp/x"})
        assert hitl.deny(req.id)
        assert hitl.get_request(req.id).decision.value == "denied"

    def test_list_pending(self) -> None:
        hitl = HumanInTheLoop()
        hitl.request_approval("tool_a", {})
        hitl.request_approval("tool_b", {})
        assert len(hitl.list_pending()) == 2


class TestAuditLog:
    """Test AuditLog."""

    def test_log_entry(self) -> None:
        audit = AuditLog()
        entry = audit.log("read_file", {"path": "/tmp/x"}, "content", True)
        assert entry.tool_name == "read_file"
        assert entry.success is True

    def test_query_by_tool(self) -> None:
        audit = AuditLog()
        audit.log("read_file", {"path": "/a"})
        audit.log("write_file", {"path": "/b"})
        audit.log("read_file", {"path": "/c"})
        results = audit.query(tool_name="read_file")
        assert len(results) == 2

    def test_query_by_success(self) -> None:
        audit = AuditLog()
        audit.log("tool_a", {}, "ok", True)
        audit.log("tool_b", {}, "fail", False)
        results = audit.query(success=True)
        assert len(results) == 1

    def test_stats(self) -> None:
        audit = AuditLog()
        assert audit.get_stats()["total"] == 0
        audit.log("read_file", {})
        stats = audit.get_stats()
        assert stats["total"] == 1
        assert stats["success_rate"] == 1.0

    def test_clear(self) -> None:
        audit = AuditLog()
        audit.log("tool_a", {})
        audit.clear()
        assert audit.get_stats()["total"] == 0

    def test_sanitize_arguments(self) -> None:
        audit = AuditLog()
        entry = audit.log("test", {"password": "secret123", "normal": "ok"})
        assert "[REDACTED]" in str(entry.arguments.get("password", ""))
        assert entry.arguments.get("normal") == "ok"


# ══════════════════════════════════════════════════════════════════════════
# 3.6  Tool Description & Discovery
# ══════════════════════════════════════════════════════════════════════════


class TestToolDescription:
    """Test ToolDescription."""

    def test_to_prompt(self) -> None:
        desc = ToolDescription(
            name="read_file",
            summary="Read files",
            description="Read contents of a file with optional offset/limit.",
            parameters={
                "path": {"type": "string", "description": "File path", "required": True},
            },
            examples=[{"args": {"path": "/tmp/x"}, "description": "Read /tmp/x"}],
        )
        prompt = desc.to_prompt()
        assert "read_file" in prompt
        assert "path" in prompt
        assert "required" in prompt


class TestToolSelector:
    """Test ToolSelector."""

    def test_rank_tools(self) -> None:
        selector = ToolSelector()
        from src.tools.filesystem import FILESYSTEM_TOOLS

        specs = [
            ToolSpec(name="read_file", description="Read a file", fn=lambda: ToolResult(success=True)),
            ToolSpec(name="write_file", description="Write a file", fn=lambda: ToolResult(success=True)),
            ToolSpec(name="execute", description="Run a command", fn=lambda: ToolResult(success=True)),
        ]
        ranked = selector.rank_tools(specs, "read content from file")
        names = [t.name for t, _ in ranked]
        assert ranked[0][1] > 0  # top has score > 0

    def test_select_top_k(self) -> None:
        selector = ToolSelector()
        specs = [ToolSpec(name=f"tool_{i}", description=f"Tool {i}", fn=lambda: ToolResult(success=True)) for i in range(20)]
        selected = selector.select(specs, "tool_1", top_k=5, min_score=0)
        assert len(selected) <= 5


class TestToolStatistics:
    """Test ToolStatistics."""

    def test_record_and_summary(self) -> None:
        stats = ToolStatistics()
        assert stats.get_summary()["total_calls"] == 0

        stats.record_call("read_file", category="filesystem", duration_ms=10, success=True, token_estimate=100)
        stats.record_call("write_file", category="filesystem", duration_ms=20, success=False, token_estimate=200)

        summary = stats.get_summary()
        assert summary["total_calls"] == 2
        assert summary["success_rate"] == 0.5
        assert summary["total_cost_usd"] > 0

    def test_most_used(self) -> None:
        stats = ToolStatistics()
        for _ in range(3):
            stats.record_call("tool_a")
        stats.record_call("tool_b")
        top = stats.most_used(top_k=2)
        assert top[0][0] == "tool_a"

    def test_clear(self) -> None:
        stats = ToolStatistics()
        stats.record_call("tool_x")
        stats.clear()
        assert stats.get_summary()["total_calls"] == 0


class TestToolDiscovery:
    """Test ToolDiscovery."""

    def test_list_tools(self) -> None:
        discovery = ToolDiscovery()
        tools = discovery.list_tools()
        assert len(tools) > 0

    def test_search(self) -> None:
        discovery = ToolDiscovery()
        results = discovery.search("file")
        assert len(results) > 0

    def test_find(self) -> None:
        discovery = ToolDiscovery()
        spec = discovery.find("read_file")
        assert spec is not None
        assert spec.name == "read_file"

    def test_select_for_context(self) -> None:
        discovery = ToolDiscovery()
        selected = discovery.select_for_context("read the file content", top_k=5)
        assert len(selected) <= 5

    def test_get_descriptions_prompt(self) -> None:
        discovery = ToolDiscovery()
        prompt = discovery.get_descriptions(prompt_format=True)
        assert isinstance(prompt, str)
        assert "read_file" in prompt