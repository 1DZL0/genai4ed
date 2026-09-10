from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Defaults are the local development values, so the stack starts with no .env
    and no API key. Boundary decisions still open with the school (concept note
    S7) live here as configuration rather than as constants in code.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://genai4ed:genai4ed@127.0.0.1:5433/genai4ed"

    llm_provider: str = "stub"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # localhost and 127.0.0.1 are the same machine to a person and different
    # origins to a browser. Allowing only one produces a silent CORS failure
    # that looks like a blank page.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    dev_identity_header: str = "X-GenAI4ED-Pseudonym"

    exploratory_chat_retention_days: int = 7
    submitted_work_retention_days: int = 365

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
