from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Defaults are the local development values, so the stack starts
    with no .env and no API key."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://genai4ed:genai4ed@127.0.0.1:5433/genai4ed"

    # "auto" uses OpenRouter when a key is set and the scripted demo agent otherwise.
    agent_client: str = "auto"
    openrouter_api_key: str = ""
    # Any OpenRouter model id that follows JSON schemas and reads images.
    openrouter_model: str = "anthropic/claude-sonnet-5"
    # A whole lesson brief from a slow model can take over a minute.
    openrouter_timeout_s: float = 60.0

    # While a study is active the researcher assigns each student a condition per lesson.
    study_active: bool = False
    # Assignment is a function of this and the student, so it can be re-derived.
    study_seed: str = "genai4ed"
    # "ladder" fixes the help sequence for everyone; "free" lets the agent choose.
    study_policy: str = "ladder"
    # Off only for simulations: conflicts are still recorded, but nothing is held back.
    study_supervisor: bool = True
    # Whether a reply that breaks the teacher's rules is redrafted or held back. Off, every
    # check still runs and is recorded but the student sees the model's reply as it was.
    # Never off with real students.
    supervisor_enforce: bool = True
    # Opens the researcher's summary and export. Unset, they do not exist.
    research_key: str = ""

    # Largest teaching material a teacher can upload, in megabytes.
    material_max_mb: int = 10

    # localhost and 127.0.0.1 are different origins to a browser; allowing only one fails silently.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Any username and password get in, creating the account on first use. Demos only.
    demo_sign_in: bool = False

    # Keys the join-code digests; changing it invalidates every issued code.
    secret_key: str = "dev-only-secret-change-me"
    sign_in_hours: int = 12
    # True once the app is only ever reached over HTTPS.
    cookie_secure: bool = False

    # Trust a pseudonym sent in a header, with no sign-in. Test suite and scripted demo only.
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
