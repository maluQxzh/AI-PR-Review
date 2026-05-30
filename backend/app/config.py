from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    github_token: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model_fast: str = "gpt-4.1-mini"
    llm_model_strong: str = "gpt-4.1"
    llm_timeout_seconds: float = 180
    llm_retry_timeout_seconds: float = 90
    # Q&A
    llm_model_multimodal: str = "gpt-4.1"
    llm_qa_temperature: float = 0.3
    llm_max_context_messages: int = 20
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'ai_pr_review.db').as_posix()}"
    max_files: int = 80
    max_patch_chars: int = 14000
    max_context_files: int = 20
    max_context_file_chars: int = 40000
    max_related_files: int = 12
    max_history_items: int = 10
    max_github_pages: int = 4
    allow_localhost_dev_origins: bool = True

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
