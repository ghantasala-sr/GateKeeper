from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root so docker compose and the app share it.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str
    anthropic_api_key: str = ""
    chat_model: str = "claude-opus-5-5"

    okta_issuer: str = ""
    okta_client_id: str = ""
    okta_client_secret: str = ""
    okta_redirect_uri: str = "http://localhost:8000/auth/okta/callback"

    session_secret: str


settings = Settings()
