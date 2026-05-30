from typing import Any

import httpx

from app.config import get_settings
from app.github.parser import PullRequestRef


class GitHubClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def fetch_pull_request(self, ref: PullRequestRef) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"

        base = f"https://api.github.com/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
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

    async def _get_paginated(self, client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while page <= 4:
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
