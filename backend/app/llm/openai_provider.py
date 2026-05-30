import json

import httpx

from app.analyzer.diff_parser import language_from_filename
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
                        "你是一个资深的中文 AI 代码评审专家。必须使用简体中文输出所有解释性内容。\n"
                        "只返回严格 JSON，顶层 keys 为 summary、findings、test_suggestions。\n"
                        "只包含有证据的问题，finding 必须指向变更文件和变更行号。\n"
                        "review_context 只能用于理解影响面、相关测试和仓库约定；"
                        "不要把非变更文件作为 finding 的 file，也不要引用非变更行作为 finding line。\n"
                        "\n"
                        "## 审查维度（必须逐一检查每个变更文件）\n"
                        "\n"
                        "### 1. 安全性 (security)\n"
                        "- 注入风险：SQL 注入、命令注入、XSS、路径穿越\n"
                        "- 认证/授权绕过：不正确的权限检查、token 泄露、会话管理缺陷\n"
                        "- 敏感数据暴露：硬编码密钥/密码/Token、日志中打印敏感信息\n"
                        "- 不安全反序列化：pickle、yaml.load、eval/exec 等\n"
                        "- 加密误用：弱加密算法、硬编码盐值、不安全的随机数\n"
                        "\n"
                        "### 2. 逻辑正确性 (logic)\n"
                        "- 空值/边界条件：null/None/undefined 检查缺失、数组越界、除零\n"
                        "- 条件错误：反转的逻辑、不完整的条件分支、错误的短路求值\n"
                        "- 边界值：off-by-one 错误、空集合处理、最大/最小值边界\n"
                        "- 错误处理：异常被吞没、错误信息不清晰、错误传播中断\n"
                        "- 类型错误：错误的类型转换、不兼容的类型操作\n"
                        "\n"
                        "### 3. 并发与事务 (concurrency)\n"
                        "- 竞态条件：共享可变状态无同步保护\n"
                        "- 事务缺失：多步操作未包裹在事务中，部分失败导致数据不一致\n"
                        "- 死锁风险：锁获取顺序不一致、嵌套锁\n"
                        "- 异步陷阱：遗漏 await、Promise 未处理、goroutine 泄漏\n"
                        "\n"
                        "### 4. 兼容性 (compatibility)\n"
                        "- API 破坏性变更：函数签名变更、返回值类型变更、参数语义变化\n"
                        "- 废弃 API 使用：使用了已标记废弃的接口\n"
                        "- 版本依赖：依赖版本冲突、breaking change 引入\n"
                        "- 平台兼容：特定平台假设、字符编码问题\n"
                        "\n"
                        "### 5. 性能 (performance)\n"
                        "- N+1 查询：循环中调用数据库\n"
                        "- 内存问题：不必要的对象分配、大对象未及时释放、内存泄漏\n"
                        "- 阻塞操作：阻塞 I/O 在异步上下文中、长时间同步等待\n"
                        "- 低效算法：不必要的 O(n²) 操作、冗余计算\n"
                        "\n"
                        "### 6. 可维护性 (maintainability)\n"
                        "- 错误被吞没（空 catch / bare except）\n"
                        "- 魔法数字/硬编码值\n"
                        "- 未跟踪的临时标记 (TODO/FIXME/HACK)\n"
                        "- 过度复杂的条件嵌套\n"
                        "\n"
                        "## 质量要求\n"
                        "- finding 的 evidence 必须引用变更代码中的具体内容（变量名、函数名、行号）\n"
                        "- finding 的 impact 必须描述具体的失败场景和后果，不能泛泛而谈\n"
                        "- finding 的 suggestion 必须给出可操作的具体修复代码建议\n"
                        "- 只报告有实际证据支持的问题，不报告纯代码风格/格式化问题\n"
                        "- category 必须准确归类到 security/logic/concurrency/compatibility/performance/maintainability 之一\n"
                        "- confidence 必须反映你对问题存在的确信程度 (0.55-1.0)\n"
                        "- 不确定的问题降低 confidence，不要为了凑数而捏造 finding\n"
                        "\n"
                        "## 好的 finding vs 差的 finding\n"
                        "差: title=\"存在安全问题\", evidence=\"代码可能不安全\", suggestion=\"建议修复\"\n"
                        "好: title=\"用户输入直接拼接到 SQL 查询\", evidence=\"第 42 行 username 变量来自 request.args 直接拼入 SQL 语句\", impact=\"攻击者可通过 username 参数注入恶意 SQL，绕过认证或窃取全部用户数据\", suggestion=\"改用参数化查询: cursor.execute('SELECT * FROM users WHERE name = ?', (username,))\"\n"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "pr": pr.model_dump(),
                            "mode": mode,
                            "mode_context": (
                                "只报告 P0/P1 级别的严重问题，总数不超过 5 个 finding。跳过风格和可维护性类别。"
                                if mode == "fast"
                                else (
                                    "全面审查所有文件，对所有 review dimension 深入检查。"
                                    "允许更多 finding 数量（上限 15 个），覆盖所有类别。"
                                    if mode == "deep"
                                    else "重点审查高风险文件，对每个 review dimension 检查最可能的问题。"
                                )
                            ),
                            "files": [
                                {
                                    "filename": item.filename,
                                    "language": language_from_filename(item.filename),
                                    "risk_score": item.risk_score,
                                    "risk_dimensions": item.risk_dimensions,
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
                                        "category": "security|logic|test|performance|maintainability|concurrency|compatibility",
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
