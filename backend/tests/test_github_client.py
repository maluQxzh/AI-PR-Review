import asyncio
import base64
from types import SimpleNamespace

from app.github.client import GitHubClient
from app.github.parser import PullRequestRef


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


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


def test_fetch_pull_request_keeps_all_paginated_files_before_review_budget(monkeypatch):
    class PaginatedClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None):
            page = (params or {}).get("page")
            self.__class__.calls.append((url, page))
            if url.endswith("/pulls/7"):
                return FakeResponse(
                    200,
                    {
                        "title": "Large PR",
                        "body": "",
                        "user": {"login": "octo"},
                        "base": {"ref": "main", "sha": "base", "repo": {"default_branch": "main"}},
                        "head": {"ref": "feature", "sha": "head"},
                        "html_url": "https://github.test/o/r/pull/7",
                    },
                )
            if url.endswith("/files"):
                if page == 1:
                    return FakeResponse(200, [_file_payload(index) for index in range(100)])
                if page == 2:
                    return FakeResponse(200, [_file_payload(index) for index in range(100, 120)])
                return FakeResponse(200, [])
            if url.endswith("/commits"):
                return FakeResponse(200, [])
            return FakeResponse(404, {})

    monkeypatch.setattr("app.github.client.httpx.AsyncClient", PaginatedClient)
    monkeypatch.setattr(
        "app.github.client.get_settings",
        lambda: SimpleNamespace(github_token=None, max_files=3, max_github_pages=2),
    )

    result = asyncio.run(GitHubClient().fetch_pull_request(PullRequestRef("o", "r", 7)))

    assert len(result["files"]) == 120
    assert result["files"][119]["filename"] == "src/file_119.py"


def _file_payload(index):
    return {
        "filename": f"src/file_{index}.py",
        "status": "modified",
        "additions": 1,
        "deletions": 0,
        "patch": "@@ -1 +1 @@\n+print('x')\n",
    }
