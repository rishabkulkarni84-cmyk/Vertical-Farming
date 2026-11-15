"""Application settings loaded from environment variables (see .env.example)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Verdant — Space-Adaptive Vertical Farming"
    environment: str = "development"
    database_url: str = f"sqlite:///{BASE_DIR / 'verdant.db'}"
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"  # replaced by .secret_key if left as is
    access_token_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    storage_dir: str = str(BASE_DIR / "storage")
    max_upload_mb: int = 8
    auto_migrate: bool = True
    simulator_enabled: bool = True
    cookie_secure: bool = False
    # Optional external providers. Leave empty to use transparent fallbacks.
    market_api_url: str = ""
    market_api_key: str = ""
    object_detector_model_path: str = ""
    # Optional server-wide AI provider (users can also add their own key in Settings → AI assistant)
    ai_provider: str = ""  # gemini | anthropic | openai
    ai_api_key: str = ""
    ai_model: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


DEFAULT_SECRET = "change-me-in-production-please-use-a-long-random-string"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.secret_key == DEFAULT_SECRET and s.environment != "test":
        # Never sign sessions with the published example key: create a random one once and keep it.
        import secrets
        path = BASE_DIR / ".secret_key"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(48))
            try:
                path.chmod(0o600)
            except OSError:
                pass
        s.secret_key = path.read_text().strip()
    return s
