import asyncio
import json

from app.llm.openai_provider import OpenAICompatibleProvider
from app.models.schemas import ChangedFile, PrInfo


class FakeSettings:
    llm_api_key = "test-key"
    llm_base_url = "https://example.test/v1"
    llm_model_fast = "fast-model"
    llm_model_strong = "strong-model"
    llm_timeout_seconds = 30
    max_patch_chars = 2000


class FakeResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class FakeAsyncClient:
    content = ""
    post_count = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        self.__class__.post_count += 1
        return FakeResponse(self.content)


def _payload(generated_artifacts) -> str:
    return json.dumps(
        {
            "summary": {
                "what_changed": "Changed auth.",
                "risk_overview": "Review auth carefully.",
                "review_focus": ["security"],
            },
            "findings": [],
            "test_suggestions": [],
            "generated_artifacts": generated_artifacts,
        }
    )


def test_provider_accepts_generated_artifacts_in_single_response(monkeypatch):
    FakeAsyncClient.post_count = 0
    FakeAsyncClient.content = _payload(
        {
            "pr_metadata": {
                "suggested_title": "security: harden auth",
                "pr_type": "security",
                "labels": [{"name": "area:security", "reason": "Auth changed", "confidence": 0.8}],
            }
        }
    )
    monkeypatch.setattr("app.llm.openai_provider.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.llm.openai_provider.httpx.AsyncClient", FakeAsyncClient)

    output = asyncio.run(OpenAICompatibleProvider().review(_pr(), _files(), "standard"))

    assert FakeAsyncClient.post_count == 1
    assert output is not None
    assert output.generated_artifacts is not None
    assert output.generated_artifacts["pr_metadata"]["pr_type"] == "security"


def test_provider_ignores_invalid_generated_artifacts_without_losing_review(monkeypatch):
    FakeAsyncClient.post_count = 0
    FakeAsyncClient.content = _payload("invalid-artifact-shape")
    monkeypatch.setattr("app.llm.openai_provider.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.llm.openai_provider.httpx.AsyncClient", FakeAsyncClient)

    output = asyncio.run(OpenAICompatibleProvider().review(_pr(), _files(), "standard"))

    assert FakeAsyncClient.post_count == 1
    assert output is not None
    assert output.summary.what_changed == "Changed auth."
    assert output.generated_artifacts is None


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
