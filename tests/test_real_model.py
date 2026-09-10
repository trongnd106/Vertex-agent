"""RED: Test real model connection with config values from .env.

This test demonstrates that the config system should be able to load
BASE_URL, API_KEY, and AGENT_MODEL from .env and use them to make
a real LLM call.

Expected to fail initially because src/config.py does not yet have
BASE_URL and API_KEY fields.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from langchain_openai import ChatOpenAI


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear env vars that might interfere, then reload config fresh."""
    # Don't clear AGENT_MODEL — it's the primary model.
    for k in list(os.environ):
        if k.startswith("OPENAI_"):
            monkeypatch.delenv(k, raising=False)


def _remove_env() -> None:
    """Remove .env so previous runs don't interfere."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        env_path.unlink()


def _write_env(content: str) -> None:
    """Write .env for the test duration."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    env_path.write_text(content)


class TestRealModelConnection:
    """Verify that config values create a working real-model connection."""

    def test_greeting_response_from_env_configured_model(self) -> None:
        """Given .env with BASE_URL, API_KEY, AGENT_MODEL,
        when we build a ChatOpenAI client from those values,
        then the model returns a non-empty greeting response."""
        _remove_env()
        _write_env(
            "LLM_PROVIDER=LiteLLM\n"
            "LLM_MODEL=deepseek-v4-flash\n"
            "LITELLM_BASE_URL=http://lite-llm.sme.staging.local\n"
            "LITELLM_API_KEY=sk-1234\n"
        )

        # Reload config so it picks up the new .env
        from src.config import config

        config.reload()

        # Assert config has the new fields
        assert hasattr(config, "LLM_PROVIDER"), "config should have LLM_PROVIDER"
        assert hasattr(config, "LLM_MODEL"), "config should have LLM_MODEL"
        assert hasattr(config, "LITELLM_BASE_URL"), "config should have LITELLM_BASE_URL"
        assert hasattr(config, "LITELLM_API_KEY"), "config should have LITELLM_API_KEY"
        assert config.LLM_PROVIDER == "LiteLLM"
        assert config.LLM_MODEL == "deepseek-v4-flash"
        assert config.LITELLM_BASE_URL == "http://lite-llm.sme.staging.local"
        assert config.LITELLM_API_KEY == "sk-1234"

        # Use the config values to build a real client (ChatOpenAI-compatible via LiteLLM proxy)
        client = ChatOpenAI(
            model=config.LLM_MODEL,
            openai_api_key=config.LITELLM_API_KEY,
            openai_api_base=config.LITELLM_BASE_URL,
        )

        # Call the model with a simple prompt
        response = client.invoke("Say exactly 'Hello from DeepSeek' and nothing else")

        # Assert we got a meaningful response
        assert response.content, "Model response should not be empty"
        assert isinstance(response.content, str)
        assert len(response.content) > 0, "Response should have content"

        # Clean up
        _remove_env()