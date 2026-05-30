import json

import httpx

from app.config import get_settings
from app.llm.base import ReviewOutput
from app.models.schemas import ChangedFile, PrInfo


class OpenAICompatibleProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def review(
        self,
        pr: PrInfo,
        files: list[ChangedFile],
        mode: str,
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

        async with httpx.AsyncClient(timeout=timeout_seconds or self.settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json=payload,
            )
            response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        return ReviewOutput.model_validate_json(content)

    async def qa(
        self,
        question: str,
        report_context: dict,
        conversation_history: list[dict] | None = None,
        qa_type: str = "qa",
        target: dict | None = None,
        image_urls: list[str] | None = None,
        model: str | None = None,
    ) -> str | None:
        if not self.settings.llm_api_key:
            return None

        history = (conversation_history or [])[-self.settings.llm_max_context_messages :]

        system_prompt = (
            "你是 AI PR Review 的中文问答助手。根据提供的报告上下文回答问题。"
            "必须使用简体中文输出。回答应简洁、具体，引用报告中的文件路径和行号。"
            "如果信息不足以回答问题，请诚实说明，不要编造。"
        )
        if qa_type == "fix_request":
            system_prompt += (
                " 用户要求你生成修复代码。请提供具体的修复方案，"
                "优先使用 diff 格式展示改动，并解释修复思路。"
            )
        elif qa_type == "test_gen":
            system_prompt += (
                " 用户要求你生成测试用例。请提供完整可运行的测试代码，"
                "包含必要的 import、setup 和断言，覆盖正常路径和边界情况。"
            )

        user_content = json.dumps(
            {
                "report": report_context,
                "conversation": history,
                "question": question,
                "target": target,
            },
            ensure_ascii=False,
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if image_urls and any(image_urls):
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_content},
                    *[
                        {"type": "image_url", "image_url": {"url": url}}
                        for url in image_urls
                        if url
                    ],
                ],
            })
            use_model = model or self.settings.llm_model_multimodal
        else:
            for h in history:
                messages.append({"role": h["role"], "content": h["content"]})
            messages.append({"role": "user", "content": user_content})
            use_model = model or self.settings.llm_model_strong

        payload = {
            "model": use_model,
            "temperature": self.settings.llm_qa_temperature,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json=payload,
            )
            response.raise_for_status()

        return response.json()["choices"][0]["message"]["content"]

    def model_for_mode(self, mode: str) -> str:
        return self.settings.llm_model_fast if mode == "fast" else self.settings.llm_model_strong
