"""Configuration management — layered config with hot reload.

Provides:
- ``ConfigLayer`` — default / env / file / runtime layers
- ``ConfigManager`` — layered resolution with env var interpolation
- ``ConfigValidator`` — schema validation with required fields
- ``ProviderConfig`` — AI provider settings
- ``AgentConfig`` — middleware, tools, profiles
- ``DeploymentConfig`` — server, database, scaling
- ``ConfigWatcher`` — hot reload via file mtime polling
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.tools.filesystem import ToolResult


# ── Config layer ──────────────────────────────────────────────────────


class ConfigLayer(Enum):
    DEFAULT = 0  # Hard-coded defaults
    ENV = 1  # Environment variables
    FILE = 2  # Config files (YAML, JSON, TOML, .env)
    RUNTIME = 3  # Runtime overrides


# ── Config manager ────────────────────────────────────────────────────


class ConfigManager:
    """Layered configuration with env var interpolation and hot reload.

    Layers (lowest → highest priority):
    1. DEFAULT — hard-coded defaults
    2. ENV — environment variables (``${VAR_NAME}`` syntax)
    3. FILE — config files (JSON, YAML, TOML, .env)
    4. RUNTIME — programmatic runtime overrides
    """

    def __init__(self) -> None:
        self._layers: dict[ConfigLayer, dict[str, Any]] = {
            ConfigLayer.DEFAULT: {},
            ConfigLayer.ENV: {},
            ConfigLayer.FILE: {},
            ConfigLayer.RUNTIME: {},
        }
        self._watchers: list[Callable[[dict[str, Any]], None]] = []
        self._lock = threading.RLock()
        self._load_env()

    def _load_env(self) -> None:
        """Load environment variables that match AGENT_* / DATABASE_* / etc."""
        env_layer: dict[str, Any] = {}
        for key, value in os.environ.items():
            env_layer[key] = value
        self._layers[ConfigLayer.ENV] = env_layer

    # ── Setting values ────────────────────────────────────────────────

    def set_default(self, key: str, value: Any) -> None:
        """Set a default value (lowest priority)."""
        with self._lock:
            self._layers[ConfigLayer.DEFAULT][key] = value

    def set_defaults(self, values: dict[str, Any]) -> None:
        """Set multiple default values."""
        with self._lock:
            self._layers[ConfigLayer.DEFAULT].update(values)

    def set(self, key: str, value: Any, layer: ConfigLayer = ConfigLayer.RUNTIME) -> None:
        """Set a value at the specified layer.

        Args:
            key: Config key.
            value: Config value.
            layer: Layer to set at (default RUNTIME, highest priority).
        """
        with self._lock:
            self._layers[layer][key] = value

    def set_many(self, values: dict[str, Any], layer: ConfigLayer = ConfigLayer.RUNTIME) -> None:
        with self._lock:
            self._layers[layer].update(values)

    # ── Getting values ────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value, checking layers highest priority first.

        Args:
            key: Config key.
            default: Fallback value if not found.

        Returns:
            The resolved value, or default.
        """
        with self._lock:
            for layer in (
                ConfigLayer.RUNTIME,
                ConfigLayer.FILE,
                ConfigLayer.ENV,
                ConfigLayer.DEFAULT,
            ):
                if key in self._layers[layer]:
                    value = self._layers[layer][key]
                    return self._interpolate(value)
        return default

    def get_all(self) -> dict[str, Any]:
        """Get merged config across all layers."""
        merged: dict[str, Any] = {}
        for layer in (
            ConfigLayer.DEFAULT,
            ConfigLayer.ENV,
            ConfigLayer.FILE,
            ConfigLayer.RUNTIME,
        ):
            for key, value in self._layers[layer].items():
                if isinstance(value, str) and "${" in value:
                    value = self._interpolate(value)
                merged[key] = value
        return merged

    def get_section(self, prefix: str) -> dict[str, Any]:
        """Get all config keys with a given prefix.

        Args:
            prefix: Key prefix (e.g. ``"database"``).

        Returns:
            Dict of matching keys (prefix stripped).
        """
        result: dict[str, Any] = {}
        prefix = prefix.rstrip(".") + "."
        for key, value in self.get_all().items():
            if key.startswith(prefix):
                result[key[len(prefix):]] = value
        return result

    # ── File loading ──────────────────────────────────────────────────

    def load_file(self, filepath: str) -> bool:
        """Load a config file into the FILE layer.

        Supported formats: ``.json``, ``.yaml``/``.yml``, ``.toml``, ``.env``.

        Args:
            filepath: Path to config file.

        Returns:
            True if loaded successfully.
        """
        if not os.path.isfile(filepath):
            return False
        try:
            ext = os.path.splitext(filepath)[1].lower()
            if ext == ".json":
                with open(filepath) as f:
                    data = json.load(f)
            elif ext in (".yaml", ".yml"):
                import yaml
                with open(filepath) as f:
                    data = yaml.safe_load(f) or {}
            elif ext == ".toml":
                import tomllib
                with open(filepath, "rb") as f:
                    data = tomllib.load(f)
            elif ext == ".env":
                data = self._load_dotenv(filepath)
            else:
                return False

            with self._lock:
                self._layers[ConfigLayer.FILE].update(self._flatten_dict(data))
            return True
        except Exception:
            return False

    def _load_dotenv(self, filepath: str) -> dict[str, str]:
        """Load a .env file into a dict."""
        result: dict[str, str] = {}
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("\"'")
                    result[key] = value
        return result

    def _flatten_dict(self, d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Flatten a nested dict into dot-separated keys."""
        result: dict[str, Any] = {}
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.update(self._flatten_dict(value, full_key))
            else:
                result[full_key] = value
        return result

    def _interpolate(self, value: Any, _depth: int = 0) -> Any:
        """Resolve ``${VAR_NAME}`` references in strings.

        Uses ``os.environ`` for direct env lookup; falls back to config
        lookup one level deep to prevent infinite recursion.
        """
        if not isinstance(value, str) or "${" not in value:
            return value
        if _depth > 3:
            return value

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            # First try environment
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            # Then try config (one level deep)
            with self._lock:
                for layer in (
                    ConfigLayer.RUNTIME,
                    ConfigLayer.FILE,
                    ConfigLayer.ENV,
                    ConfigLayer.DEFAULT,
                ):
                    if var_name in self._layers[layer]:
                        nested = self._layers[layer][var_name]
                        if isinstance(nested, str) and "${" in nested:
                            return self._interpolate(nested, _depth + 1)
                        return str(nested) if nested is not None else match.group(0)
            return match.group(0)

        return re.sub(r"\$\{([^}]+)\}", replacer, value)

    # ── Hot reload ────────────────────────────────────────────────────

    def watch(self, filepath: str, callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        """Set up a watcher for config file changes.

        Args:
            filepath: Path to watch.
            callback: Called with updated config on change.
        """
        watcher = ConfigWatcher(filepath, self, callback or (lambda d: None))
        watcher.start()

    def on_change(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback for any config change.

        Args:
            callback: Called with the full merged config on change.
        """
        with self._lock:
            self._watchers.append(callback)

    def _notify(self, old: dict[str, Any], new: dict[str, Any]) -> None:
        if old == new:
            return
        with self._lock:
            watchers = list(self._watchers)
        for cb in watchers:
            try:
                cb(new)
            except Exception:
                pass

    # ── Validation ────────────────────────────────────────────────────

    def validate(self, schema: dict[str, Any]) -> list[str]:
        """Validate config against a schema.

        Args:
            schema: Dict mapping key → expected type (as string like
                   ``"string"``, ``"int"``, ``"list"``, or a list of
                   strings for enum).

        Returns:
            List of validation error messages (empty if valid).
        """
        errors: list[str] = []
        all_config = self.get_all()
        for key, expected in schema.items():
            value = all_config.get(key)
            if value is None:
                errors.append(f"Missing required key: {key}")
                continue
            if isinstance(expected, str):
                type_map = {
                    "string": str, "str": str,
                    "int": int, "integer": int,
                    "float": float, "number": (int, float),
                    "bool": bool, "boolean": bool,
                    "list": list, "array": list,
                    "dict": dict, "object": dict,
                }
                expected_type = type_map.get(expected.lower())
                if expected_type and not isinstance(value, expected_type):
                    errors.append(
                        f"Key '{key}': expected {expected}, got {type(value).__name__}"
                    )
            elif isinstance(expected, list):
                if value not in expected:
                    errors.append(
                        f"Key '{key}': must be one of {expected}, got {value}"
                    )
        return errors


# ── Config watcher ────────────────────────────────────────────────────


class ConfigWatcher:
    """Polls a config file for changes and triggers a callback.

    Useful for hot-reload without restart.
    """

    def __init__(
        self,
        filepath: str,
        manager: ConfigManager,
        callback: Callable[[dict[str, Any]], None],
        interval: float = 5.0,
    ) -> None:
        self._filepath = filepath
        self._manager = manager
        self._callback = callback
        self._interval = interval
        self._last_mtime: float = 0.0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start watching in a daemon thread."""
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _poll(self) -> None:
        while self._running:
            try:
                if os.path.isfile(self._filepath):
                    mtime = os.path.getmtime(self._filepath)
                    if mtime > self._last_mtime:
                        old = self._manager.get_all()
                        self._manager.load_file(self._filepath)
                        new = self._manager.get_all()
                        self._callback(new)
                        self._last_mtime = mtime
            except Exception:
                pass
            time.sleep(self._interval)


# ── Provider configuration ────────────────────────────────────────────


@dataclass
class ProviderConfig:
    """AI provider configuration.

    Attributes:
        name: Provider name (``"openai"``, ``"anthropic"``, etc.).
        api_key: API key (resolved from env if ``${VAR}``).
        base_url: Custom API endpoint.
        default_model: Default model name.
        extra: Provider-specific extra parameters.
    """

    name: str = "openai"
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, manager: ConfigManager, prefix: str = "provider") -> ProviderConfig:
        """Load provider config from a ``ConfigManager``.

        Args:
            manager: Config manager instance.
            prefix: Key prefix (e.g. ``"provider.openai"``).

        Returns:
            A ``ProviderConfig``.
        """
        section = manager.get_section(prefix)
        return cls(
            name=section.get("name", prefix.split(".")[-1]),
            api_key=section.get("api_key", ""),
            base_url=section.get("base_url", ""),
            default_model=section.get("default_model", ""),
            extra={k: v for k, v in section.items() if k not in ("name", "api_key", "base_url", "default_model")},
        )


# ── Agent configuration ───────────────────────────────────────────────


@dataclass
class AgentConfig:
    """Agent-level configuration.

    Attributes:
        middleware: List of middleware names/classes to enable.
        tool_permissions: Dict of tool name → permission level.
        profiles: List of profile names to apply.
        max_iterations: Max execution steps per agent run.
        system_prompt: Override system prompt.
        model: Model override.
    """

    middleware: list[str] = field(default_factory=list)
    tool_permissions: dict[str, str] = field(default_factory=dict)
    profiles: list[str] = field(default_factory=list)
    max_iterations: int = 100
    system_prompt: str = ""
    model: str = ""

    @classmethod
    def from_config(cls, manager: ConfigManager, prefix: str = "agent") -> AgentConfig:
        section = manager.get_section(prefix)
        return cls(
            middleware=manager.get(f"{prefix}.middleware", []),
            tool_permissions=manager.get(f"{prefix}.tool_permissions", {}),
            profiles=manager.get(f"{prefix}.profiles", []),
            max_iterations=int(manager.get(f"{prefix}.max_iterations", 100)),
            system_prompt=manager.get(f"{prefix}.system_prompt", ""),
            model=manager.get(f"{prefix}.model", ""),
        )


# ── Deployment configuration ──────────────────────────────────────────


@dataclass
class DeploymentConfig:
    """Deployment-level configuration.

    Attributes:
        server_host: HTTP server host.
        server_port: HTTP server port.
        database_url: Postgres connection string.
        redis_url: Redis connection string.
        log_level: Logging level.
        max_concurrency: Max concurrent agent executions.
        environment: ``"dev"``, ``"staging"``, or ``"production"``.
        workspace_dir: Default workspace directory.
    """

    server_host: str = "0.0.0.0"
    server_port: int = 8000
    database_url: str = ""
    redis_url: str = ""
    log_level: str = "INFO"
    max_concurrency: int = 10
    environment: str = "dev"
    workspace_dir: str = "./workspace"

    @classmethod
    def from_config(cls, manager: ConfigManager, prefix: str = "deployment") -> DeploymentConfig:
        section = manager.get_section(prefix)
        return cls(
            server_host=section.get("server_host", "0.0.0.0"),
            server_port=int(section.get("server_port", 8000)),
            database_url=section.get("database_url", ""),
            redis_url=section.get("redis_url", ""),
            log_level=section.get("log_level", "INFO"),
            max_concurrency=int(section.get("max_concurrency", 10)),
            environment=section.get("environment", "dev"),
            workspace_dir=section.get("workspace_dir", "./workspace"),
        )


# ── Pre-built defaults ────────────────────────────────────────────────


def create_default_config() -> ConfigManager:
    """Create a ``ConfigManager`` with sensible defaults pre-set.

    Returns:
        A pre-configured ``ConfigManager``.
    """
    manager = ConfigManager()
    manager.set_defaults(
        {
            "agent.max_iterations": 100,
            "agent.middleware": "security,tool_injection,summarization,progress",
            "provider.openai.name": "openai",
            "provider.openai.default_model": "gpt-4o",
            "provider.anthropic.name": "anthropic",
            "provider.anthropic.default_model": "claude-sonnet-4-20250514",
            "deployment.server_host": "0.0.0.0",
            "deployment.server_port": 8000,
            "deployment.log_level": "INFO",
            "deployment.max_concurrency": 10,
            "deployment.environment": "dev",
            "deployment.workspace_dir": "./workspace",
            "database.url": "postgresql://postgres:postgres@localhost:5432/vertex",
            "database.pool_size": 10,
            "database.vector_dim": 1536,
        }
    )
    return manager


__all__ = [
    "AgentConfig",
    "ConfigLayer",
    "ConfigManager",
    "ConfigWatcher",
    "DeploymentConfig",
    "ProviderConfig",
    "create_default_config",
]