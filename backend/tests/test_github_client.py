import asyncio
import base64

from app.github.client import GitHubClient


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncClient:
    payload = {}
    status_code = 200

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, *args, **kwargs):
        return FakeResponse(self.status_code, self.payload)


def test_fetch_file_text_decodes_utf8_content(monkeypatch):
    content = base64.b64encode("hello\nworld\n".encode()).decode()
    FakeAsyncClient.status_code = 200
    FakeAsyncClient.payload = {"type": "file", "size": 12, "content": content}
    monkeypatch.setattr("app.github.client.httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(GitHubClient().fetch_file_text("o", "r", "README.md", "main"))

    assert result["content"] == "hello\nworld\n"
    assert result["note"] is None


def test_fetch_file_text_skips_binary_content(monkeypatch):
    content = base64.b64encode(b"\x00\x01binary").decode()
    FakeAsyncClient.status_code = 200
    FakeAsyncClient.payload = {"type": "file", "size": 8, "content": content}
    monkeypatch.setattr("app.github.client.httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(GitHubClient().fetch_file_text("o", "r", "image.png", "main"))

    assert result["content"] is None
    assert result["note"] == "binary file skipped"


def test_fetch_file_text_degrades_on_404(monkeypatch):
    FakeAsyncClient.status_code = 404
    FakeAsyncClient.payload = {"message": "Not Found"}
    monkeypatch.setattr("app.github.client.httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(GitHubClient().fetch_file_text("o", "r", "missing.py", "main"))

    assert result["content"] is None
    assert result["note"] == "github returned 404"
