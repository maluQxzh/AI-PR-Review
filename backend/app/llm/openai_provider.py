import json

import httpx

from app.config import get_settings
from app.llm.base import ReviewOutput
from app.models.schemas import ChangedFile, PrInfo, ReviewContext


class OpenAICompatibleProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def review(
        self,
        pr: PrInfo,
        files: list[ChangedFile],
        mode: str,
        review_context: ReviewContext | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ReviewOutput | None:
        if not self.settings.llm_api_key:
            return None

        payload = {
            "model": model or self.model_for_mode(mode),
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个中文 AI 代码评审助手。必须使用简体中文输出所有解释性内容。"
                        "只返回严格 JSON，顶层 keys 为 summary、findings、test_suggestions。"
                        "只包含有证据的问题，finding 必须指向变更文件和变更行号。"
                        "review_context 只能用于理解影响面、相关测试和仓库约定；"
                        "不要把非变更文件作为 finding 的 file，也不要引用非变更行作为 finding line。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "pr": pr.model_dump(),
                            "mode": mode,
                            "files": [
                                {
                                    "filename": item.filename,
                                    "risk_score": item.risk_score,
                                    "risk_reasons": item.risk_reasons,
                                    "patch": (item.patch or "")[: self.settings.max_patch_chars],
                                    "context": item.context.model_dump() if item.context else None,
                                }
                                for item in files
                            ],
                            "review_context": self._compact_review_context(review_context),
                            "schema": {
                                "summary": {
                                    "what_changed": "string",
                                    "risk_overview": "string",
                                    "review_focus": ["string"],
                                },
                                "findings": [
                                    {
                                        "title": "string",
                                        "severity": "P0|P1|P2|P3",
                                        "confidence": 0.8,
                                        "category": "security|logic|test|performance|maintainability",
                                        "file": "path",
                                        "line": 10,
                                        "evidence": "string",
                                        "impact": "string",
                                        "suggestion": "string",
                                        "comment_draft": "string",
                                    }
                                ],
                                "test_suggestions": [
                                    {
                                        "title": "string",
                                        "reason": "string",
                                        "suggested_case": "string",
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }

        async with httpx.AsyncClient(timeout=timeout_seconds or self.settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json=payload,
            )
            response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        return ReviewOutput.model_validate_json(content)

    def model_for_mode(self, mode: str) -> str:
        return self.settings.llm_model_fast if mode == "fast" else self.settings.llm_model_strong

    def _compact_review_context(self, review_context: ReviewContext | None) -> dict | None:
        if not review_context:
            return None
        payload = review_context.model_dump()
        for doc in payload.get("repository_docs", []):
            doc["content"] = (doc.get("content") or "")[:6000]
        for item in payload.get("history", []):
            item["summary"] = (item.get("summary") or "")[:500]
        return payload
