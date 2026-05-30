import asyncio

import httpx

from app.analyzer import reviewer
from app.llm.base import ReviewOutput
from app.models.schemas import ChangedFile, PrInfo, Summary


class FakeSettings:
    llm_api_key = "test-key"
    llm_model_fast = "fast-model"
    llm_model_strong = "strong-model"
    llm_timeout_seconds = 180
    llm_retry_timeout_seconds = 90


class RetryProvider:
    def __init__(self) -> None:
        self.settings = FakeSettings()

    def model_for_mode(self, mode: str) -> str:
        return self.settings.llm_model_fast if mode == "fast" else self.settings.llm_model_strong

    async def review(self, pr, files, mode, model=None, timeout_seconds=None):
        if model == self.settings.llm_model_strong:
            raise httpx.ReadTimeout("slow model")
        return ReviewOutput(
            summary=Summary(
                what_changed="Changed code.",
                risk_overview="Fast retry completed.",
                review_focus=["retry"],
            ),
            findings=[],
            test_suggestions=[],
        )


class NoKeySettings(FakeSettings):
    llm_api_key = None


class NoKeyProvider(RetryProvider):
    def __init__(self) -> None:
        self.settings = NoKeySettings()


def test_review_pr_retries_fast_model_after_strong_timeout(monkeypatch):
    monkeypatch.setattr(reviewer, "OpenAICompatibleProvider", RetryProvider)

    output = asyncio.run(reviewer.review_pr(_pr(), _files(), "standard"))

    assert output.source == "llm_fast_retry"
    assert "strong model timed out" in (output.source_detail or "")


def test_review_pr_records_no_key_fallback(monkeypatch):
    monkeypatch.setattr(reviewer, "OpenAICompatibleProvider", NoKeyProvider)

    output = asyncio.run(reviewer.review_pr(_pr(), _files(), "standard"))

    assert output.source == "fallback"
    assert output.source_detail == "fallback_no_key: LLM_API_KEY is not configured."


def _pr() -> PrInfo:
    return PrInfo(owner="demo", repo="repo", number=1, title="Demo PR")


def _files() -> list[ChangedFile]:
    return [
        ChangedFile(
            filename="src/app.py",
            status="modified",
            additions=1,
            patch="@@ -1 +1 @@\n+print('hello')\n",
        )
    ]
