"""Central configuration — singleton that all modules read from.

Replaces scattered ``os.environ.get()`` calls across the codebase.
Loads from environment variables, ``.env`` file, and optionally YAML config.

Usage::

    from src.config import config

    db_url = config.DATABASE_URL
    model  = config.AGENT_MODEL
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _str_to_bool(v: str | bool) -> bool:
    if isinstance(v, bool):
        return v
    return v.lower() in ("1", "true", "yes", "on")


def _load_dotenv(filepath: str | Path) -> None:
    """Load a ``.env`` file into ``os.environ`` (idempotent)."""
    path = Path(filepath)
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        # Don't overwrite values already set in the environment
        if key not in os.environ:
            os.environ[key] = value


# Auto-load .env at import time (idempotent, lowest priority)
_env_path = Path(__file__).resolve().parent.parent / ".env"
_load_dotenv(_env_path)


@dataclass
class _Config:
    # ── Agent Model ────────────────────────────────────────────
    AGENT_MODEL: str = field(
        default_factory=lambda: os.environ.get("AGENT_MODEL", "openai:gpt-4o-mini")
    )
    """LLM model string: ``<provider>:<model-name>``."""

    # ── Database ───────────────────────────────────────────────
    DATABASE_URL: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "")
    )
    """Postgres connection string for checkpointer + store."""

    # ── Redis ──────────────────────────────────────────────────
    REDIS_URL: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "")
    )

    # ── API Server ─────────────────────────────────────────────
    SERVER_HOST: str = field(
        default_factory=lambda: os.environ.get("SERVER_HOST", "0.0.0.0")
    )
    SERVER_PORT: int = field(
        default_factory=lambda: int(os.environ.get("SERVER_PORT", "8000"))
    )
    CORS_ORIGINS: str = field(
        default_factory=lambda: os.environ.get("CORS_ORIGINS", "*")
    )
    AUTH_TOKEN: str = field(
        default_factory=lambda: os.environ.get("AUTH_TOKEN", "")
    )
    PORT: int = field(
        default_factory=lambda: int(os.environ.get("PORT", "3000"))
    )
    """Alternative webhook port (Telegram webhook)."""

    # ── Telegram Bot ───────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = field(
        default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", "")
    )
    TELEGRAM_ALLOWED_IDS: str = field(
        default_factory=lambda: os.environ.get("TELEGRAM_ALLOWED_IDS", "")
    )
    TELEGRAM_WEBHOOK_SECRET: str = field(
        default_factory=lambda: os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    )

    # ── Search Providers ───────────────────────────────────────
    TAVILY_API_KEY: str = field(
        default_factory=lambda: os.environ.get("TAVILY_API_KEY", "")
    )

    # ── LLM Provider Selection ─────────────────────────────────
    LLM_PROVIDER: str = field(
        default_factory=lambda: os.environ.get("LLM_PROVIDER", "OpenRouter")
    )
    """Provider name: OpenRouter, OpenAI, LiteLLM, Gemini."""

    # ── LLM Provider Keys ──────────────────────────────────────
    OPENAI_API_KEY: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    ANTHROPIC_API_KEY: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )

    # ── OpenRouter ─────────────────────────────────────────────
    OPENROUTER_API_KEY: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", "")
    )
    OPENROUTER_MODEL: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat")
    )

    # ── OpenAI (direct) ────────────────────────────────────────
    OPENAI_MODEL: str = field(
        default_factory=lambda: os.environ.get("OPENAI_MODEL", "gpt-4o")
    )
    OPENAI_BASE_URL: str = field(
        default_factory=lambda: os.environ.get("OPENAI_BASE_URL", "")
    )

    # ── Gemini ─────────────────────────────────────────────────
    GEMINI_API_KEY: str = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY", "")
    )
    GEMINI_MODEL: str = field(
        default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
    )

    # ── LiteLLM ────────────────────────────────────────────────
    LLM_MODEL: str = field(
        default_factory=lambda: os.environ.get("LLM_MODEL", "")
    )
    """Model name for LiteLLM provider."""
    LITELLM_BASE_URL: str = field(
        default_factory=lambda: os.environ.get("LITELLM_BASE_URL", "")
    )
    LITELLM_API_KEY: str = field(
        default_factory=lambda: os.environ.get("LITELLM_API_KEY", "")
    )

    # ── Base URL / API Key (generic, for test compatibility) ───
    BASE_URL: str = field(
        default_factory=lambda: os.environ.get("BASE_URL", "")
    )
    API_KEY: str = field(
        default_factory=lambda: os.environ.get("API_KEY", "")
    )

    # ── LangSmith ──────────────────────────────────────────────
    LANGSMITH_TRACING: bool = field(
        default_factory=lambda: _str_to_bool(os.environ.get("LANGSMITH_TRACING", "false"))
    )
    LANGSMITH_API_KEY: str = field(
        default_factory=lambda: os.environ.get("LANGSMITH_API_KEY", "")
    )
    LANGSMITH_PROJECT: str = field(
        default_factory=lambda: os.environ.get("LANGSMITH_PROJECT", "vertex-agent")
    )
    LANGSMITH_ENDPOINT: str = field(
        default_factory=lambda: os.environ.get(
            "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
        )
    )

    # ── Sandbox ────────────────────────────────────────────────
    SANDBOX_TYPE: str = field(
        default_factory=lambda: os.environ.get("SANDBOX_TYPE", "local")
    )
    SANDBOX_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: int(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "30"))
    )

    # ── Dreaming ───────────────────────────────────────────────
    DREAMING_ENABLED: bool = field(
        default_factory=lambda: _str_to_bool(os.environ.get("DREAMING_ENABLED", "true"))
    )
    DREAMING_INTERVAL_SECONDS: int = field(
        default_factory=lambda: int(os.environ.get("DREAMING_INTERVAL_SECONDS", "300"))
    )
    DREAMING_BATCH_SIZE: int = field(
        default_factory=lambda: int(os.environ.get("DREAMING_BATCH_SIZE", "5"))
    )

    # ── Docker / Production ────────────────────────────────────
    WORKSPACE_DIR: str = field(
        default_factory=lambda: os.environ.get("WORKSPACE_DIR", "./workspace")
    )
    LOG_LEVEL: str = field(
        default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO")
    )
    MAX_CONCURRENCY: int = field(
        default_factory=lambda: int(os.environ.get("MAX_CONCURRENCY", "10"))
    )
    HOME_DIR: str = field(
        default_factory=lambda: os.environ.get("HOME_DIR", "./home")
    )
    """Runtime data directory (sessions, uploads, etc.)."""

    def reload(self) -> None:
        """Reload all fields from current environment variables."""
        for f in self.__dataclass_fields__:
            default_factory = self.__dataclass_fields__[f].default_factory
            if default_factory is not None:
                object.__setattr__(self, f, default_factory())


# Module-level singleton
config = _Config()
"""Singleton config instance. Import and use directly:

>>> from src.config import config
>>> config.DATABASE_URL
'postgresql://...'
>>> config.AGENT_MODEL
'openai:gpt-4o-mini'
"""

__all__ = ["config"]