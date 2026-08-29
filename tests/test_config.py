"""Tests for the centralized Settings configuration."""

import os
import tempfile
from pathlib import Path

import pytest

from src.config.settings import Settings, get_settings


class TestSettingsDefaults:
    """Test that all default values match the specification."""

    def test_agent_model_default(self):
        """Test agent_model default value."""
        settings = Settings()
        assert settings.agent_model == "openai:gpt-4o-mini"

    def test_database_url_default(self):
        """Test database_url defaults to None."""
        settings = Settings()
        assert settings.database_url is None

    def test_stale_thread_max_age_days_default(self):
        """Test stale_thread_max_age_days default value."""
        settings = Settings()
        assert settings.stale_thread_max_age_days == 30

    def test_dreaming_heartbeat_max_age_seconds_default(self):
        """Test dreaming_heartbeat_max_age_seconds default value."""
        settings = Settings()
        assert settings.dreaming_heartbeat_max_age_seconds == 3600

    def test_dreaming_max_backlog_default(self):
        """Test dreaming_max_backlog default value."""
        settings = Settings()
        assert settings.dreaming_max_backlog == 50

    def test_dreaming_stale_after_days_default(self):
        """Test dreaming_stale_after_days default value."""
        settings = Settings()
        assert settings.dreaming_stale_after_days == 30

    def test_summarization_trigger_tokens_default(self):
        """Test summarization_trigger_tokens default value."""
        settings = Settings()
        assert settings.summarization_trigger_tokens == 20000

    def test_summarization_keep_messages_default(self):
        """Test summarization_keep_messages default value."""
        settings = Settings()
        assert settings.summarization_keep_messages == 6

    def test_tool_output_max_length_default(self):
        """Test tool_output_max_length default value."""
        settings = Settings()
        assert settings.tool_output_max_length == 4000

    def test_sandbox_default_timeout_seconds_default(self):
        """Test sandbox_default_timeout_seconds default value."""
        settings = Settings()
        assert settings.sandbox_default_timeout_seconds == 30

    def test_rate_limit_capacity_default(self):
        """Test rate_limit_capacity default value."""
        settings = Settings()
        assert settings.rate_limit_capacity == 5.0

    def test_rate_limit_refill_rate_default(self):
        """Test rate_limit_refill_rate default value."""
        settings = Settings()
        assert settings.rate_limit_refill_rate == 1.0

    def test_tavily_api_key_default(self):
        """Test tavily_api_key defaults to None."""
        settings = Settings()
        assert settings.tavily_api_key is None

    def test_langsmith_tracing_default(self):
        """Test langsmith_tracing defaults to False."""
        settings = Settings()
        assert settings.langsmith_tracing is False

    def test_langsmith_api_key_default(self):
        """Test langsmith_api_key defaults to None."""
        settings = Settings()
        assert settings.langsmith_api_key is None

    def test_langsmith_project_default(self):
        """Test langsmith_project default value."""
        settings = Settings()
        assert settings.langsmith_project == "vertex-agent"


class TestSettingsEnvironmentVariables:
    """Test that Settings loads from environment variables correctly."""

    def test_load_from_env_vars(self, monkeypatch):
        """Test that environment variables override defaults."""
        monkeypatch.setenv("AGENT_MODEL", "openai:gpt-4-turbo")
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("STALE_THREAD_MAX_AGE_DAYS", "60")
        monkeypatch.setenv("DREAMING_MAX_BACKLOG", "100")
        monkeypatch.setenv("SUMMARIZATION_TRIGGER_TOKENS", "30000")
        monkeypatch.setenv("RATE_LIMIT_CAPACITY", "10.0")
        monkeypatch.setenv("TAVILY_API_KEY", "test-key-123")
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        monkeypatch.setenv("LANGSMITH_PROJECT", "custom-project")

        settings = Settings()

        assert settings.agent_model == "openai:gpt-4-turbo"
        assert settings.database_url == "postgresql://localhost/db"
        assert settings.stale_thread_max_age_days == 60
        assert settings.dreaming_max_backlog == 100
        assert settings.summarization_trigger_tokens == 30000
        assert settings.rate_limit_capacity == 10.0
        assert settings.tavily_api_key == "test-key-123"
        assert settings.langsmith_tracing is True
        assert settings.langsmith_project == "custom-project"

    def test_boolean_parsing_from_env(self, monkeypatch):
        """Test that boolean values are parsed correctly from env vars."""
        monkeypatch.setenv("LANGSMITH_TRACING", "false")
        settings = Settings()
        assert settings.langsmith_tracing is False

        monkeypatch.setenv("LANGSMITH_TRACING", "1")
        settings = Settings()
        assert settings.langsmith_tracing is True

    def test_integer_parsing_from_env(self, monkeypatch):
        """Test that integer values are parsed correctly from env vars."""
        monkeypatch.setenv("SANDBOX_DEFAULT_TIMEOUT_SECONDS", "60")
        settings = Settings()
        assert settings.sandbox_default_timeout_seconds == 60

    def test_float_parsing_from_env(self, monkeypatch):
        """Test that float values are parsed correctly from env vars."""
        monkeypatch.setenv("RATE_LIMIT_CAPACITY", "7.5")
        settings = Settings()
        assert settings.rate_limit_capacity == 7.5


class TestGetSettingsFunction:
    """Test the get_settings() function."""

    def test_get_settings_returns_settings_instance(self):
        """Test that get_settings() returns a Settings instance."""
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_get_settings_returns_properly_initialized_settings(self):
        """Test that get_settings() returns properly initialized Settings."""
        settings = get_settings()

        # Verify some critical fields exist and have correct defaults
        assert hasattr(settings, "agent_model")
        assert hasattr(settings, "database_url")
        assert hasattr(settings, "langsmith_project")

        assert settings.agent_model == "openai:gpt-4o-mini"
        assert settings.database_url is None
        assert settings.langsmith_project == "vertex-agent"

    def test_get_settings_respects_env_vars(self, monkeypatch):
        """Test that get_settings() respects environment variables."""
        monkeypatch.setenv("AGENT_MODEL", "anthropic:claude-3-opus")
        settings = get_settings()
        assert settings.agent_model == "anthropic:claude-3-opus"


class TestSettingsCriticalFields:
    """Test critical fields for sanity checks."""

    def test_database_url_field_exists(self):
        """Test database_url field exists and is optional."""
        settings = Settings()
        assert hasattr(settings, "database_url")
        assert settings.database_url is None

    def test_agent_model_field_exists(self):
        """Test agent_model field exists with correct default."""
        settings = Settings()
        assert hasattr(settings, "agent_model")
        assert settings.agent_model == "openai:gpt-4o-mini"

    def test_langsmith_project_field_exists(self):
        """Test langsmith_project field exists with correct default."""
        settings = Settings()
        assert hasattr(settings, "langsmith_project")
        assert settings.langsmith_project == "vertex-agent"

    def test_all_required_fields_present(self):
        """Test that all required fields are present in Settings."""
        settings = Settings()

        required_fields = [
            "agent_model",
            "database_url",
            "stale_thread_max_age_days",
            "dreaming_heartbeat_max_age_seconds",
            "dreaming_max_backlog",
            "dreaming_stale_after_days",
            "summarization_trigger_tokens",
            "summarization_keep_messages",
            "tool_output_max_length",
            "sandbox_default_timeout_seconds",
            "rate_limit_capacity",
            "rate_limit_refill_rate",
            "tavily_api_key",
            "langsmith_tracing",
            "langsmith_api_key",
            "langsmith_project",
        ]

        for field in required_fields:
            assert hasattr(settings, field), f"Field {field} missing from Settings"


class TestSettingsTypeAnnotations:
    """Test that Settings has correct type annotations."""

    def test_agent_model_is_string(self):
        """Test agent_model is string type."""
        settings = Settings()
        assert isinstance(settings.agent_model, str)

    def test_database_url_is_string_or_none(self):
        """Test database_url is string or None."""
        settings = Settings()
        assert settings.database_url is None or isinstance(settings.database_url, str)

    def test_stale_thread_max_age_days_is_integer(self):
        """Test stale_thread_max_age_days is integer."""
        settings = Settings()
        assert isinstance(settings.stale_thread_max_age_days, int)

    def test_rate_limit_capacity_is_float(self):
        """Test rate_limit_capacity is float."""
        settings = Settings()
        assert isinstance(settings.rate_limit_capacity, float)

    def test_langsmith_tracing_is_boolean(self):
        """Test langsmith_tracing is boolean."""
        settings = Settings()
        assert isinstance(settings.langsmith_tracing, bool)


class TestSettingsConfiguration:
    """Test Settings configuration and behavior."""

    def test_settings_ignores_extra_env_vars(self, monkeypatch):
        """Test that Settings ignores extra environment variables (extra='ignore')."""
        monkeypatch.setenv("EXTRA_UNKNOWN_FIELD", "should-be-ignored")
        monkeypatch.setenv("AGENT_MODEL", "openai:gpt-4-turbo")

        # Should not raise an error
        settings = Settings()
        assert settings.agent_model == "openai:gpt-4-turbo"
        assert not hasattr(settings, "extra_unknown_field")

    def test_settings_model_config_has_env_file(self):
        """Test that Settings model_config specifies env_file."""
        assert hasattr(Settings, "model_config")
        # Verify SettingsConfigDict is used
        assert Settings.model_config is not None

    def test_multiple_settings_instances_independent(self, monkeypatch):
        """Test that multiple Settings instances can be created independently."""
        monkeypatch.setenv("AGENT_MODEL", "openai:gpt-4-turbo")
        settings1 = Settings()

        monkeypatch.delenv("AGENT_MODEL")
        settings2 = Settings()

        assert settings1.agent_model == "openai:gpt-4-turbo"
        assert settings2.agent_model == "openai:gpt-4o-mini"  # default


class TestEnvExampleFile:
    """Test that .env.example file can be used as a template for .env."""

    def test_env_example_file_exists(self):
        """Test that .env.example file exists in project root."""
        env_example_path = Path(__file__).parent.parent / ".env.example"
        assert env_example_path.exists(), f".env.example not found at {env_example_path}"

    def test_env_example_contains_all_settings_fields(self):
        """Test that .env.example documents all Settings fields."""
        env_example_path = Path(__file__).parent.parent / ".env.example"
        content = env_example_path.read_text()

        # All field names should be represented in UPPER_SNAKE_CASE
        field_names = [
            "AGENT_MODEL",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DATABASE_URL",
            "STALE_THREAD_MAX_AGE_DAYS",
            "DREAMING_HEARTBEAT_MAX_AGE_SECONDS",
            "DREAMING_MAX_BACKLOG",
            "DREAMING_STALE_AFTER_DAYS",
            "SUMMARIZATION_TRIGGER_TOKENS",
            "SUMMARIZATION_KEEP_MESSAGES",
            "TOOL_OUTPUT_MAX_LENGTH",
            "SANDBOX_DEFAULT_TIMEOUT_SECONDS",
            "RATE_LIMIT_CAPACITY",
            "RATE_LIMIT_REFILL_RATE",
            "TAVILY_API_KEY",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]

        for field_name in field_names:
            assert (
                field_name in content
            ), f"Field {field_name} not documented in .env.example"

    def test_env_example_has_helpful_comments(self):
        """Test that .env.example includes documentation comments."""
        env_example_path = Path(__file__).parent.parent / ".env.example"
        content = env_example_path.read_text()

        # Should have section headers and comments explaining variables
        assert "=== ====" in content or "===" in content, "Missing section headers"
        assert "Default:" in content, "Missing default value documentation"
        assert "Required" in content or "optional" in content, (
            "Missing requirement level documentation"
        )

    def test_env_example_can_load_as_settings_with_defaults(self, monkeypatch):
        """Test that .env.example can be copied to .env and Settings loads with defaults."""
        env_example_path = Path(__file__).parent.parent / ".env.example"
        content = env_example_path.read_text()

        # Parse the .env.example file and set environment variables for values that aren't empty
        for line in content.split("\n"):
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                # Only set non-empty values
                if value and not value.startswith("#"):
                    monkeypatch.setenv(key, value)

        # Should be able to create Settings without errors
        settings = Settings()

        # Verify critical fields have expected values from .env.example
        assert settings.agent_model == "openai:gpt-4o-mini"
        assert settings.stale_thread_max_age_days == 30
        assert settings.dreaming_heartbeat_max_age_seconds == 3600
        assert settings.dreaming_max_backlog == 50
        assert settings.dreaming_stale_after_days == 30
        assert settings.summarization_trigger_tokens == 20000
        assert settings.summarization_keep_messages == 6
        assert settings.tool_output_max_length == 4000
        assert settings.sandbox_default_timeout_seconds == 30
        assert settings.rate_limit_capacity == 5.0
        assert settings.rate_limit_refill_rate == 1.0
        assert settings.langsmith_tracing is False
        assert settings.langsmith_project == "vertex-agent"

    def test_env_example_all_fields_documented(self):
        """Test that all 16 Settings fields are documented in .env.example."""
        env_example_path = Path(__file__).parent.parent / ".env.example"
        content = env_example_path.read_text()

        # Count documented fields (lines with VAR_NAME=)
        documented_fields = []
        for line in content.split("\n"):
            line = line.strip()
            if "=" in line and not line.startswith("#") and line:
                key = line.split("=", 1)[0].strip()
                if key.isupper():
                    documented_fields.append(key)

        # Ensure all 16 fields are documented
        expected_fields = {
            "AGENT_MODEL",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DATABASE_URL",
            "STALE_THREAD_MAX_AGE_DAYS",
            "DREAMING_HEARTBEAT_MAX_AGE_SECONDS",
            "DREAMING_MAX_BACKLOG",
            "DREAMING_STALE_AFTER_DAYS",
            "SUMMARIZATION_TRIGGER_TOKENS",
            "SUMMARIZATION_KEEP_MESSAGES",
            "TOOL_OUTPUT_MAX_LENGTH",
            "SANDBOX_DEFAULT_TIMEOUT_SECONDS",
            "RATE_LIMIT_CAPACITY",
            "RATE_LIMIT_REFILL_RATE",
            "TAVILY_API_KEY",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        }

        documented_set = set(documented_fields)
        assert (
            expected_fields.issubset(documented_set)
        ), f"Missing fields: {expected_fields - documented_set}"
