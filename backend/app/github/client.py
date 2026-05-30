import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.github.parser import PullRequestRef


class GitHubClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    async def fetch_pull_request(self, ref: PullRequestRef) -> dict[str, Any]:
        base = f"https://api.github.com/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
        async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
            pr_resp = await client.get(base)
            pr_resp.raise_for_status()
            pr = pr_resp.json()

            files = await self._get_paginated(client, f"{base}/files")
            commits = await self._get_paginated(client, f"{base}/commits")

        return {
            "owner": ref.owner,
            "repo": ref.repo,
            "number": ref.number,
            "title": pr.get("title") or "",
            "description": pr.get("body") or "",
            "author": (pr.get("user") or {}).get("login"),
            "base_branch": (pr.get("base") or {}).get("ref"),
            "head_branch": (pr.get("head") or {}).get("ref"),
            "base_sha": (pr.get("base") or {}).get("sha"),
            "head_sha": (pr.get("head") or {}).get("sha"),
            "default_branch": ((pr.get("base") or {}).get("repo") or {}).get("default_branch"),
            "html_url": pr.get("html_url"),
            "commits": [
                {
                    "sha": item.get("sha"),
                    "message": ((item.get("commit") or {}).get("message") or "").splitlines()[0],
                    "author": (((item.get("commit") or {}).get("author") or {}).get("name")),
                }
                for item in commits[:20]
            ],
            "files": [
                {
                    "filename": item.get("filename", ""),
                    "status": item.get("status", "modified"),
                    "additions": item.get("additions", 0),
                    "deletions": item.get("deletions", 0),
                    "patch": item.get("patch"),
                }
                for item in files[: self.settings.max_files]
            ],
        }

    async def fetch_file_text(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str | None,
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        if not ref:
            return {"path": path, "ref": ref, "content": None, "note": "missing ref"}

        encoded_path = quote(path, safe="/")
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"
        try:
            async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
                response = await client.get(url, params={"ref": ref})
        except httpx.HTTPError as exc:
            return {"path": path, "ref": ref, "content": None, "note": f"request failed: {exc}"}

        if response.status_code in {403, 404}:
            return {"path": path, "ref": ref, "content": None, "note": f"github returned {response.status_code}"}
        if response.status_code >= 400:
            return {"path": path, "ref": ref, "content": None, "note": f"github returned {response.status_code}"}

        payload = response.json()
        if isinstance(payload, list) or payload.get("type") != "file":
            return {"path": path, "ref": ref, "content": None, "note": "not a text file"}

        size = int(payload.get("size") or 0)
        limit = max_chars or self.settings.max_context_file_chars
        if size > limit * 4:
            return {
                "path": path,
                "ref": ref,
                "content": None,
                "note": f"file too large ({size} bytes)",
            }

        raw_content = payload.get("content") or ""
        try:
            data = base64.b64decode(raw_content, validate=False)
        except ValueError:
            return {"path": path, "ref": ref, "content": None, "note": "base64 decode failed"}
        if b"\x00" in data[:2048]:
            return {"path": path, "ref": ref, "content": None, "note": "binary file skipped"}
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return {"path": path, "ref": ref, "content": None, "note": "non-utf8 file skipped"}

        truncated = len(text) > limit
        return {
            "path": path,
            "ref": ref,
            "content": text[:limit],
            "truncated": truncated,
            "note": "truncated" if truncated else None,
        }

    async def fetch_tree(self, owner: str, repo: str, ref: str | None) -> dict[str, Any]:
        if not ref:
            return {"files": [], "truncated": False, "note": "missing ref"}
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{quote(ref, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
                response = await client.get(url, params={"recursive": "1"})
        except httpx.HTTPError as exc:
            return {"files": [], "truncated": False, "note": f"request failed: {exc}"}
        if response.status_code in {403, 404}:
            return {"files": [], "truncated": False, "note": f"github returned {response.status_code}"}
        if response.status_code >= 400:
            return {"files": [], "truncated": False, "note": f"github returned {response.status_code}"}

        payload = response.json()
        files = [
            item["path"]
            for item in payload.get("tree", [])
            if item.get("type") == "blob" and isinstance(item.get("path"), str)
        ]
        return {"files": files, "truncated": bool(payload.get("truncated")), "note": None}

    async def search_issues(
        self,
        owner: str,
        repo: str,
        terms: list[str],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clean_terms = [term for term in terms if term and len(term) >= 3][:6]
        if not clean_terms:
            return []
        query = f"repo:{owner}/{repo} {' '.join(clean_terms)}"
        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": min(limit or self.settings.max_history_items, 20),
        }
        try:
            async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
                response = await client.get("https://api.github.com/search/issues", params=params)
        except httpx.HTTPError:
            return []
        if response.status_code >= 400:
            return []
        items = response.json().get("items", [])
        return [
            {
                "title": item.get("title"),
                "html_url": item.get("html_url"),
                "state": item.get("state"),
                "updated_at": item.get("updated_at"),
                "kind": "pull_request" if item.get("pull_request") else "issue",
                "summary": (item.get("body") or "")[:280],
            }
            for item in items[: limit or self.settings.max_history_items]
        ]

    async def _get_paginated(self, client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while page <= self.settings.max_github_pages:
            response = await client.get(url, params={"per_page": 100, "page": page})
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items
