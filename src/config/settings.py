from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Model
    agent_model: str = "openai:gpt-4o-mini"

    # Database
    database_url: str | None = None

    # Session cleanup
    stale_thread_max_age_days: int = 30

    # Dreaming
    dreaming_heartbeat_max_age_seconds: int = 3600
    dreaming_max_backlog: int = 50
    dreaming_stale_after_days: int = 30

    # Context management
    summarization_trigger_tokens: int = 20000
    summarization_keep_messages: int = 6
    tool_output_max_length: int = 4000

    # Sandbox
    sandbox_default_timeout_seconds: int = 30

    # Rate limiting
    rate_limit_capacity: float = 5.0
    rate_limit_refill_rate: float = 1.0

    # Optional tools
    tavily_api_key: str | None = None

    # Observability
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "vertex-agent"


def get_settings() -> Settings:
    return Settings()
