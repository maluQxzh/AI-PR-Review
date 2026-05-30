import json

import httpx

from app.config import get_settings
from app.llm.base import ReviewOutput
from app.models.schemas import ChangedFile, PrInfo


class OpenAICompatibleProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def review(self, pr: PrInfo, files: list[ChangedFile], mode: str) -> ReviewOutput | None:
        if not self.settings.llm_api_key:
            return None

        payload = {
            "model": self.settings.llm_model_strong if mode != "fast" else self.settings.llm_model_fast,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个中文 AI 代码评审助手。必须使用简体中文输出所有解释性内容。"
                        "只返回严格 JSON，顶层 keys 为 summary、findings、test_suggestions。"
                        "只包含有证据的问题，finding 必须指向变更文件和变更行号。"
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
                                }
                                for item in files
                            ],
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

        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json=payload,
            )
            response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        return ReviewOutput.model_validate_json(content)
