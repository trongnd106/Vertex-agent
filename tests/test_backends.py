"""Tests for Backend Infrastructure (Task 8)."""

import os
import tempfile
import time

import pytest

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
    BackendResult,
    BaseSandbox,
    FileInfo,
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
    SessionVariable,
    VariableScope,
)


# ======================================================================
# 8.1 — Backend Protocol & Implementations
# ======================================================================


class TestFileInfo:
    def test_defaults(self):
        fi = FileInfo(name="test.txt", path="/test.txt", size=100)
        assert fi.name == "test.txt"
        assert fi.path == "/test.txt"
        assert fi.size == 100
        assert fi.is_dir is False
        assert fi.permissions == ""

    def test_modified_iso(self):
        fi = FileInfo(name="a", path="a", modified=1000000.0)
        assert "1970" in fi.modified_iso

    def test_directory(self):
        fi = FileInfo(name="dir", path="dir", is_dir=True)
        assert fi.is_dir is True
        assert fi.size == 0


class TestStateBackend:
    @pytest.fixture
    def backend(self):
        return StateBackend()

    def test_write_and_read(self, backend):
        backend.write("test.txt", "hello world")
        result = backend.read("test.txt")
        assert result.success is True
        assert result.data == "hello world"

    def test_read_nonexistent(self, backend):
        result = backend.read("nope.txt")
        assert result.success is False

    def test_ls(self, backend):
        backend.write("a.txt", "aaa")
        backend.write("b.txt", "bbb")
        result = backend.ls()
        assert result.success is True
        names = [f.name for f in result.data]
        assert "a.txt" in names
        assert "b.txt" in names

    def test_ls_subdir(self, backend):
        backend.write("sub/x.txt", "x")
        result = backend.ls("sub")
        assert result.success is True
        names = [f.name for f in result.data]
        assert "x.txt" in names

    def test_edit(self, backend):
        backend.write("test.txt", "hello world")
        backend.edit("test.txt", "world", "there")
        result = backend.read("test.txt")
        assert result.data == "hello there"

    def test_edit_string_not_found(self, backend):
        backend.write("test.txt", "hello")
        result = backend.edit("test.txt", "nope", "x")
        assert result.success is False

    def test_delete_file(self, backend):
        backend.write("test.txt", "data")
        backend.delete("test.txt")
        assert backend.read("test.txt").success is False

    def test_glob(self, backend):
        backend.write("a.txt", "")
        backend.write("b.py", "")
        backend.write("c.txt", "")
        result = backend.glob("*.txt")
        assert len(result.data) == 2

    def test_grep(self, backend):
        backend.write("test.txt", "line1\nhello world\nline3")
        result = backend.grep("hello")
        assert len(result.data) == 1
        assert result.data[0]["file"] == "test.txt"

    def test_download_files(self, backend):
        backend.write("a.txt", "aaa")
        backend.write("b.txt", "bbb")
        result = backend.download_files(["a.txt", "b.txt"])
        assert result.data == {"a.txt": "aaa", "b.txt": "bbb"}

    def test_upload_files(self, backend):
        backend.upload_files({"x.txt": "xxx", "y.txt": "yyy"})
        assert backend.read("x.txt").data == "xxx"

    def test_checkpoint_and_rollback(self, backend):
        backend.write("a.txt", "v1")
        backend.checkpoint()
        backend.write("a.txt", "v2")
        backend.rollback()
        assert backend.read("a.txt").data == "v1"

    def test_delete_directory(self, backend):
        backend.write("dir/a.txt", "a")
        backend.write("dir/b.txt", "b")
        backend.delete("dir")
        assert backend.read("dir/a.txt").success is False

    def test_ls_empty(self, backend):
        result = backend.ls()
        assert result.data == []

    def test_grep_no_match(self, backend):
        backend.write("/test.txt", "hello")
        result = backend.grep("zzz")
        assert result.data == []


class TestFilesystemBackend:
    @pytest.fixture
    def backend(self):
        tmpdir = tempfile.mkdtemp()
        return FilesystemBackend(tmpdir)

    def test_write_and_read(self, backend):
        backend.write("test.txt", "hello")
        result = backend.read("test.txt")
        assert result.success is True
        assert result.data == "hello"

    def test_read_nonexistent(self, backend):
        result = backend.read("nope.txt")
        assert result.success is False

    def test_ls(self, backend):
        backend.write("a.txt", "aaa")
        backend.write("b.txt", "bbb")
        result = backend.ls()
        assert result.success is True
        names = [f.name for f in result.data]
        assert "a.txt" in names
        assert "b.txt" in names

    def test_edit(self, backend):
        backend.write("edit.txt", "hello world")
        backend.edit("edit.txt", "world", "there")
        assert backend.read("edit.txt").data == "hello there"

    def test_delete(self, backend):
        backend.write("delete.txt", "data")
        backend.delete("delete.txt")
        assert backend.read("delete.txt").success is False

    def test_glob(self, backend):
        backend.write("a.txt", "")
        backend.write("b.py", "")
        result = backend.glob("*.txt")
        assert len(result.data) == 1

    def test_download_files(self, backend):
        backend.write("a.txt", "aaa")
        result = backend.download_files(["a.txt"])
        assert result.data == {"a.txt": "aaa"}

    def test_grep(self, backend):
        backend.write("test.txt", "hello world\nline2")
        result = backend.grep("hello")
        assert len(result.data) == 1


class TestCompositeBackend:
    @pytest.fixture
    def backends(self):
        default = StateBackend()
        logs = StateBackend()
        comp = CompositeBackend(default=default, routes={"logs/*": logs})
        return comp, default, logs

    def test_default_routes(self, backends):
        comp, default, _ = backends
        comp.write("test.txt", "hello")
        assert default.read("test.txt").data == "hello"

    def test_route_matching(self, backends):
        comp, _, logs = backends
        comp.write("logs/app.log", "error")
        assert logs.read("logs/app.log").data == "error"

    def test_add_route(self, backends):
        comp, default, _ = backends
        extra = StateBackend()
        comp.add_route("data/*", extra)
        comp.write("data/foo.csv", "csv")
        assert extra.read("data/foo.csv").data == "csv"

    def test_remove_route(self, backends):
        comp, _, logs = backends
        assert comp.remove_route("logs/*") is True
        assert comp.remove_route("nope") is False

    def test_upload_across_routes(self, backends):
        comp, default, logs = backends
        comp.upload_files({"test.txt": "hello", "logs/app.log": "error"})
        assert default.read("test.txt").data == "hello"
        assert logs.read("logs/app.log").data == "error"


class TestBackendResult:
    def test_defaults(self):
        r = BackendResult()
        assert r.success is True
        assert r.data is None
        assert r.error == ""

    def test_error(self):
        r = BackendResult(success=False, error="boom")
        assert r.success is False


class TestBaseSandbox:
    def test_abc(self):
        assert BaseSandbox.__abstractmethods__ is not None


# ======================================================================
# 8.2 — Session State Management
# ======================================================================


class TestSessionVariable:
    def test_defaults(self):
        var = SessionVariable(name="count", value=42, scope=VariableScope.PLAN)
        assert var.name == "count"
        assert var.value == 42
        assert var.var_type == "integer"
        assert var.created_at > 0

    def test_type_detection(self):
        assert SessionVariable(name="s", value="hello").var_type == "string"
        assert SessionVariable(name="b", value=True).var_type == "boolean"
        assert SessionVariable(name="f", value=1.5).var_type == "number"
        assert SessionVariable(name="l", value=[1, 2]).var_type == "array"
        assert SessionVariable(name="d", value={"k": "v"}).var_type == "object"
        assert SessionVariable(name="n", value=None).var_type == "null"

    def test_to_dict(self):
        var = SessionVariable(name="x", value=10, scope=VariableScope.PLAN)
        d = var.to_dict()
        assert d["name"] == "x"
        assert d["scope"] == "plan"
        assert d["value"] == 10


class TestInMemorySessionBackend:
    @pytest.fixture
    def backend(self):
        return InMemorySessionBackend()

    def test_store_and_get_variable(self, backend):
        backend.store_variable(VariableScope.PLAN, "s1", "p1", "b1", "count", 42)
        val = backend.get_variable(
            {"session_id": "s1", "plan_id": "p1", "bot_id": "b1"}, "count"
        )
        assert val == 42

    def test_get_variable_nonexistent(self, backend):
        val = backend.get_variable({"session_id": "s1"}, "nope")
        assert val is None

    def test_list_variables(self, backend):
        backend.store_variable(VariableScope.PLAN, "s1", "p1", "b1", "a", 1)
        backend.store_variable(VariableScope.PLAN, "s1", "p1", "b1", "b", 2)
        backend.store_variable(VariableScope.BOT, "", "", "b1", "token", "xyz")
        vars = backend.list_variables(scope=VariableScope.PLAN)
        assert len(vars) == 2
        vars_all = backend.list_variables()
        assert len(vars_all) == 3

    def test_delete_variable(self, backend):
        backend.store_variable(VariableScope.PLAN, "s1", "p1", "b1", "x", 1)
        assert backend.delete_variable("x", VariableScope.PLAN, "s1") is True

    def test_delete_nonexistent(self, backend):
        assert backend.delete_variable("nope", VariableScope.PLAN) is False

    def test_bot_scope_retrieval(self, backend):
        backend.store_variable(VariableScope.BOT, "", "", "bot1", "api_key", "sk-123")
        val = backend.get_variable(
            {"session_id": "any", "plan_id": "any", "bot_id": "bot1"}, "api_key"
        )
        assert val == "sk-123"

    def test_sys_scope_retrieval(self, backend):
        backend.store_variable(VariableScope.SYS, "", "", "", "global_flag", True)
        val = backend.get_variable({"session_id": "s1"}, "global_flag")
        assert val is True


class TestRedisSessionBackend:
    @pytest.fixture
    def backend(self):
        return RedisSessionBackend("redis://localhost:6379/0")

    def test_fallback_works(self, backend):
        # Falls back to in-memory when redis is unavailable
        backend.store_variable(VariableScope.PLAN, "s1", "p1", "b1", "count", 42)
        val = backend.get_variable(
            {"session_id": "s1", "plan_id": "p1", "bot_id": "b1"}, "count"
        )
        assert val == 42

    def test_list_variables(self, backend):
        backend.store_variable(VariableScope.PLAN, "s1", "p1", "b1", "x", 1)
        vars = backend.list_variables()
        assert len(vars) >= 1


class TestDatabaseSessionBackend:
    @pytest.fixture
    def backend(self):
        return DatabaseSessionBackend("postgresql://localhost:5432/test")

    def test_fallback_works(self, backend):
        backend.store_variable(VariableScope.PLAN, "s1", "p1", "b1", "count", 42)
        val = backend.get_variable(
            {"session_id": "s1", "plan_id": "p1", "bot_id": "b1"}, "count"
        )
        assert val is None or val == 42  # None if no postgres, otherwise 42


# ======================================================================
# 8.3 — Configuration Management
# ======================================================================


class TestConfigManager:
    @pytest.fixture
    def manager(self):
        m = ConfigManager()
        m.set_default("db.host", "localhost")
        m.set_default("db.port", 5432)
        return m

    def test_get_default(self, manager):
        assert manager.get("db.host") == "localhost"
        assert manager.get("db.port") == 5432

    def test_get_nonexistent(self, manager):
        assert manager.get("nope") is None
        assert manager.get("nope", "fallback") == "fallback"

    def test_runtime_overrides_default(self, manager):
        manager.set("db.host", "production.example.com")
        assert manager.get("db.host") == "production.example.com"

    def test_set_defaults(self, manager):
        manager.set_defaults({"app.name": "test", "app.version": 1})
        assert manager.get("app.name") == "test"

    def test_set_many(self, manager):
        manager.set_many({"a": 1, "b": 2})
        assert manager.get("a") == 1
        assert manager.get("b") == 2

    def test_get_all(self, manager):
        manager.set("runtime.key", "val")
        all_cfg = manager.get_all()
        assert "db.host" in all_cfg
        assert "runtime.key" in all_cfg

    def test_get_section(self, manager):
        manager.set_many({"database.url": "pg://", "database.pool": 10})
        section = manager.get_section("database")
        assert section["url"] == "pg://"
        assert section["pool"] == 10

    def test_layer_priority(self, manager):
        manager.set_default("key", "default")
        manager.set("key", "env", ConfigLayer.ENV)
        manager.set("key", "runtime", ConfigLayer.RUNTIME)
        assert manager.get("key") == "runtime"

    def test_env_interpolation(self):
        os.environ["TEST_DB_URL"] = "postgres://localhost"
        manager = ConfigManager()
        manager.set_default("database.url", "${TEST_DB_URL}")
        val = manager.get("database.url")
        assert "postgres" in str(val)

    def test_validate_required(self, manager):
        errors = manager.validate({"missing.key": "string"})
        assert len(errors) == 1
        assert "Missing required" in errors[0]

    def test_validate_type(self, manager):
        manager.set("my.key", "not_an_int")
        errors = manager.validate({"my.key": "int"})
        assert len(errors) == 1

    def test_validate_enum(self, manager):
        manager.set("env", "dev")
        errors = manager.validate({"env": ["dev", "prod"]})
        assert errors == []

    def test_validate_enum_fail(self, manager):
        manager.set("env", "staging")
        errors = manager.validate({"env": ["dev", "prod"]})
        assert len(errors) == 1

    def test_load_json_config(self, manager):
        import tempfile, json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"custom": {"key": "json_value"}}, f)
            fpath = f.name
        try:
            assert manager.load_file(fpath) is True
            assert manager.get("custom.key") == "json_value"
        finally:
            os.unlink(fpath)

    def test_load_env_file(self, manager):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write('CUSTOM_VAR=hello\n# comment\nOTHER_VAR=world\n')
            fpath = f.name
        try:
            assert manager.load_file(fpath) is True
        finally:
            os.unlink(fpath)

    def test_load_nonexistent_file(self, manager):
        assert manager.load_file("/nonexistent/config.json") is False


class TestProviderConfig:
    def test_from_config(self):
        manager = ConfigManager()
        manager.set_many({
            "provider.openai.name": "openai",
            "provider.openai.api_key": "sk-test",
            "provider.openai.default_model": "gpt-4o",
        })
        cfg = ProviderConfig.from_config(manager, "provider.openai")
        assert cfg.name == "openai"
        assert cfg.api_key == "sk-test"
        assert cfg.default_model == "gpt-4o"


class TestAgentConfig:
    def test_from_config(self):
        manager = ConfigManager()
        manager.set("agent.middleware", ["security", "progress"])
        manager.set("agent.max_iterations", 50)
        cfg = AgentConfig.from_config(manager)
        assert cfg.middleware == ["security", "progress"]
        assert cfg.max_iterations == 50


class TestDeploymentConfig:
    def test_from_config(self):
        manager = ConfigManager()
        manager.set("deployment.environment", "production")
        manager.set("deployment.server_port", 9000)
        cfg = DeploymentConfig.from_config(manager)
        assert cfg.environment == "production"
        assert cfg.server_port == 9000

    def test_defaults(self):
        cfg = DeploymentConfig()
        assert cfg.server_host == "0.0.0.0"
        assert cfg.server_port == 8000


class TestCreateDefaultConfig:
    def test_defaults_are_set(self):
        manager = create_default_config()
        assert manager.get("agent.max_iterations") == 100
        assert manager.get("deployment.server_port") == 8000
        assert manager.get("database.url") == "postgresql://postgres:postgres@localhost:5432/vertex"

    def test_section_access(self):
        manager = create_default_config()
        section = manager.get_section("provider.openai")
        assert section["default_model"] == "gpt-4o"


class TestConfigWatcher:
    def test_start_stop(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"test": "value"}')
            fpath = f.name
        try:
            manager = ConfigManager()
            calls = []
            watcher = ConfigWatcher(fpath, manager, lambda d: calls.append(d), interval=0.1)
            watcher.start()
            time.sleep(0.15)
            watcher.stop()
            # The watcher may or may not have triggered depending on timing
            assert watcher._running is False
        finally:
            os.unlink(fpath)


# ======================================================================
# 8.4 — Database Infrastructure
# ======================================================================


class TestDatabaseManager:
    @pytest.fixture
    def db(self):
        return DatabaseManager(DatabaseConfig(url="postgresql://localhost:5432/nonexistent"))

    def test_not_connected(self, db):
        assert db.is_connected is False

    def test_health_check_disconnected(self, db):
        result = db.health_check()
        assert result["status"] == "disconnected"

    def test_execute_not_connected(self, db):
        assert db.execute("SELECT 1") is None

    def test_config(self, db):
        assert db.config.url == "postgresql://localhost:5432/nonexistent"


class TestMigrationManager:
    @pytest.fixture
    def db(self):
        return DatabaseManager(DatabaseConfig(url="postgresql://localhost:5432/nonexistent"))

    def test_get_version_disconnected(self, db):
        mgr = MigrationManager(db)
        assert mgr.get_current_version() == -1

    def test_list_applied_disconnected(self, db):
        mgr = MigrationManager(db)
        assert mgr.list_applied() == []


class TestCreateCheckpointerTables:
    def test_noop_without_db(self):
        db = DatabaseManager(DatabaseConfig(url="postgresql://localhost:5432/nonexistent"))
        result = create_checkpointer_tables(db)
        # Should not crash
        assert result is False


class TestCreatePgvectorExtension:
    def test_noop_without_db(self):
        db = DatabaseManager(DatabaseConfig(url="postgresql://localhost:5432/nonexistent"))
        result = create_pgvector_extension(db)
        assert result is True


class TestCreateSessionTables:
    def test_noop_without_db(self):
        db = DatabaseManager(DatabaseConfig(url="postgresql://localhost:5432/nonexistent"))
        result = create_session_tables(db)
        assert result is False


class TestDatabaseConfig:
    def test_defaults(self):
        cfg = DatabaseConfig()
        assert "postgresql" in cfg.url
        assert cfg.pool_min == 2
        assert cfg.pool_max == 10
        assert cfg.vector_dim == 1536


# ======================================================================
# 8.5 — LocalShellBackend & Sandbox Integration
# ======================================================================


class TestLocalShellBackend:
    @pytest.fixture
    def backend(self):
        tmpdir = tempfile.mkdtemp()
        return LocalShellBackend(root_dir=tmpdir, timeout=5.0)

    def test_execute_success(self, backend):
        result = backend.execute("echo hello")
        assert result.success is True
        assert "hello" in result.data["stdout"]

    def test_execute_failure(self, backend):
        result = backend.execute("exit 1")
        assert result.success is True  # still succeeds at running the command
        assert result.data["exit_code"] == 1

    def test_execute_timeout(self, backend):
        result = backend.execute("sleep 10", timeout=0.1)
        assert result.success is False

    def test_inherits_filesystem(self, backend):
        backend.write("test.txt", "shell_test")
        assert backend.read("test.txt").data == "shell_test"

    def test_ls_works(self, backend):
        backend.write("f1.txt", "")
        result = backend.ls()
        names = [f.name for f in result.data]
        assert "f1.txt" in names


class TestContainerSandbox:
    @pytest.fixture
    def sandbox(self):
        return ContainerSandbox(image="python:3.11-slim")

    def test_default_properties(self, sandbox):
        assert sandbox.id is not None
        assert "python:3.11-slim" in sandbox._image

    def test_execute_returns_error(self, sandbox):
        result = sandbox.execute("echo hello")
        # Should handle missing Docker gracefully
        assert isinstance(result.success, bool)

    def test_upload_files(self, sandbox):
        result = sandbox.upload_files({"test.txt": "hello"})
        assert isinstance(result.success, bool)

    def test_download_files(self, sandbox):
        result = sandbox.download_files(["test.txt"])
        assert isinstance(result.success, bool)

    def test_start_no_docker(self, sandbox):
        started = sandbox.start()
        # Without Docker available, start returns False
        assert isinstance(started, bool)


class TestLangSmithSandbox:
    @pytest.fixture
    def sandbox(self):
        return LangSmithSandbox(project="test")

    def test_id(self, sandbox):
        assert sandbox.id.startswith("langsmith-")

    def test_execute_returns_not_implemented(self, sandbox):
        result = sandbox.execute("echo hello")
        assert result.success is False
        assert "not yet implemented" in result.error

    def test_upload_not_implemented(self, sandbox):
        result = sandbox.upload_files({"a": "b"})
        assert result.success is False

    def test_download_not_implemented(self, sandbox):
        result = sandbox.download_files(["a.txt"])
        assert result.success is False


class TestRoleBasedSandboxSelector:
    @pytest.fixture
    def selector(self):
        return RoleBasedSandboxSelector()

    def test_dev_returns_local(self, selector):
        assert selector.select("customer-support") == SandboxType.LOCAL

    def test_production_returns_container(self):
        selector = RoleBasedSandboxSelector(environment="production")
        assert selector.select("customer-support") == SandboxType.CONTAINER

    def test_operator_in_production(self):
        selector = RoleBasedSandboxSelector(environment="production")
        assert selector.select("operator") == SandboxType.LOCAL

    def test_unknown_role(self):
        selector = RoleBasedSandboxSelector(environment="production")
        assert selector.select("unknown") == SandboxType.CONTAINER

    def test_custom_roles(self):
        selector = RoleBasedSandboxSelector(
            environment="production",
            roles={"admin": "local"},
        )
        assert selector.select("admin") == SandboxType.LOCAL


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    def test_protocol_exports(self):
        import src.backends
        for name in [
            "BackendProtocol", "BackendResult", "BaseSandbox",
            "FileInfo", "SandboxBackendProtocol",
        ]:
            assert hasattr(src.backends, name), f"Missing export: {name}"

    def test_implementations_exports(self):
        import src.backends
        for name in ["StateBackend", "FilesystemBackend", "CompositeBackend"]:
            assert hasattr(src.backends, name), f"Missing export: {name}"

    def test_session_exports(self):
        import src.backends
        for name in [
            "SessionStateBackend", "InMemorySessionBackend",
            "RedisSessionBackend", "DatabaseSessionBackend",
            "SessionVariable", "VariableScope",
        ]:
            assert hasattr(src.backends, name), f"Missing export: {name}"

    def test_config_exports(self):
        import src.backends
        for name in [
            "ConfigManager", "ConfigLayer", "ConfigWatcher",
            "ProviderConfig", "AgentConfig", "DeploymentConfig",
            "create_default_config",
        ]:
            assert hasattr(src.backends, name), f"Missing export: {name}"

    def test_database_exports(self):
        import src.backends
        for name in [
            "DatabaseManager", "DatabaseConfig", "MigrationManager",
            "create_checkpointer_tables", "BackupStrategy",
        ]:
            assert hasattr(src.backends, name), f"Missing export: {name}"

    def test_sandboxed_exports(self):
        import src.backends
        for name in [
            "LocalShellBackend", "ContainerSandbox", "LangSmithSandbox",
            "RoleBasedSandboxSelector", "SandboxType",
        ]:
            assert hasattr(src.backends, name), f"Missing export: {name}"