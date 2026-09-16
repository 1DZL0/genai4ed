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

    # The class agent's model. "auto" uses OpenRouter when a key is set and the
    # scripted demo agent otherwise; "openrouter" or "scripted" force one.
    agent_client: str = "auto"
    openrouter_api_key: str = ""
    # Needs to follow JSON schemas and read images. Any OpenRouter model id.
    openrouter_model: str = "anthropic/claude-sonnet-5"
    # Largest teaching material a teacher can upload, in megabytes.
    material_max_mb: int = 10

    # localhost and 127.0.0.1 are the same machine to a person and different
    # origins to a browser. Allowing only one produces a silent CORS failure
    # that looks like a blank page.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Demo sign-in: any username and any password get in, creating the account
    # on first use. For trying the platform out only - it checks nothing.
    demo_sign_in: bool = False

    # Keys the join-code digests. Changing it invalidates every issued code.
    secret_key: str = "dev-only-secret-change-me"
    sign_in_hours: int = 12
    # True once the app is only ever reached over HTTPS end to end.
    cookie_secure: bool = False

    # Off everywhere except the test suite and the scripted demo: when on, the
    # backend trusts a pseudonym sent in a header, with no sign-in at all.
    dev_identity_enabled: bool = False
    dev_identity_header: str = "X-GenAI4ED-Pseudonym"

    exploratory_chat_retention_days: int = 7
    submitted_work_retention_days: int = 365

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
