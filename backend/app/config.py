from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    github_token: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model_fast: str = "gpt-4.1-mini"
    llm_model_strong: str = "gpt-4.1"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'ai_pr_review.db').as_posix()}"
    max_files: int = 80
    max_patch_chars: int = 14000

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
