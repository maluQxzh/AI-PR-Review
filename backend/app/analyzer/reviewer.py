import logging
from collections.abc import Callable

import httpx

from app.analyzer.diff_parser import extract_added_lines
from app.llm.base import ReviewOutput
from app.llm.openai_provider import OpenAICompatibleProvider
from app.models.schemas import ChangedFile, Finding, PrInfo, ReviewContext, Summary, TestSuggestion

logger = logging.getLogger(__name__)
StatusCallback = Callable[[int, str], None]


async def review_pr(
    pr: PrInfo,
    files: list[ChangedFile],
    mode: str,
    review_context: ReviewContext | None = None,
    status_callback: StatusCallback | None = None,
) -> ReviewOutput:
    provider = OpenAICompatibleProvider()
    top_n = 0 if mode == "fast" else (15 if mode == "deep" else 5)
    review_targets = files[:top_n] if top_n else []
    selected_files = review_targets or files[:5]

    if not provider.settings.llm_api_key:
        logger.info("LLM review skipped because LLM_API_KEY is not configured.")
        fallback = _heuristic_review(pr, files, review_targets)
        fallback.source_detail = "fallback_no_key: LLM_API_KEY is not configured."
        return fallback

    primary_model = provider.model_for_mode(mode)
    _notify(status_callback, 70, f"正在生成评审建议（{primary_model}）")

    try:
        output = await _provider_review(
            provider,
            pr,
            selected_files,
            mode,
            review_context,
            model=primary_model,
            timeout_seconds=provider.settings.llm_timeout_seconds,
        )
        if output:
            output.source = "llm"
            output.source_detail = f"llm: {primary_model} completed successfully."
            return output
        logger.info("LLM review skipped because provider returned no output.")
    except Exception as exc:
        if mode != "fast" and isinstance(exc, httpx.ReadTimeout):
            retry = await _retry_fast_model(provider, pr, selected_files, mode, review_context, status_callback)
            if retry:
                return retry
            fallback = _heuristic_review(pr, files, review_targets)
            fallback.source_detail = (
                f"fallback_timeout: {primary_model} timed out after "
                f"{provider.settings.llm_timeout_seconds}s and fast retry failed."
            )
            return fallback
        if isinstance(exc, httpx.ReadTimeout):
            fallback = _heuristic_review(pr, files, review_targets)
            fallback.source_detail = (
                f"fallback_timeout: {primary_model} timed out after "
                f"{provider.settings.llm_timeout_seconds}s."
            )
            return fallback
        # Demo fallback: keep the report useful when LLM credentials/network are unavailable.
        logger.warning("LLM review failed; falling back to rule-based review: %s", exc, exc_info=True)

    fallback = _heuristic_review(pr, files, review_targets)
    fallback.source_detail = "fallback_api_error: LLM review failed before producing usable output."
    return fallback


async def _retry_fast_model(
    provider: OpenAICompatibleProvider,
    pr: PrInfo,
    files: list[ChangedFile],
    mode: str,
    review_context: ReviewContext | None,
    status_callback: StatusCallback | None,
) -> ReviewOutput | None:
    logger.warning(
        "LLM review timed out after %ss; retrying with fast model.",
        provider.settings.llm_timeout_seconds,
    )
    _notify(status_callback, 82, f"强模型超时，正在切换 {provider.settings.llm_model_fast} 重试")
    try:
        output = await _provider_review(
            provider,
            pr,
            files,
            mode,
            review_context,
            model=provider.settings.llm_model_fast,
            timeout_seconds=provider.settings.llm_retry_timeout_seconds,
        )
        if output:
            output.source = "llm_fast_retry"
            output.source_detail = (
                f"llm_fast_retry: strong model timed out after "
                f"{provider.settings.llm_timeout_seconds}s; "
                f"{provider.settings.llm_model_fast} completed successfully."
            )
            return output
    except Exception as exc:
        logger.warning("Fast LLM retry failed; falling back to rule-based review: %s", exc, exc_info=True)
    return None


def _notify(status_callback: StatusCallback | None, progress: int, step: str) -> None:
    if status_callback:
        status_callback(progress, step)


async def _provider_review(
    provider: OpenAICompatibleProvider,
    pr: PrInfo,
    files: list[ChangedFile],
    mode: str,
    review_context: ReviewContext | None,
    model: str,
    timeout_seconds: float,
) -> ReviewOutput | None:
    kwargs = {"model": model, "timeout_seconds": timeout_seconds}
    if review_context is not None:
        kwargs["review_context"] = review_context
    return await provider.review(pr, files, mode, **kwargs)


def _heuristic_review(pr: PrInfo, files: list[ChangedFile], review_targets: list[ChangedFile]) -> ReviewOutput:
    high_files = [file for file in files if file.risk_level in {"high", "critical"}]
    focus = _focus_from_reasons(files)
    summary = Summary(
        what_changed=(
            f"PR #{pr.number} 共修改 {len(files)} 个文件，主要涉及 "
            f"{', '.join(file.filename for file in files[:3]) or '暂无文件'}。"
        ),
        risk_overview=(
            f"规则分析识别出 {len(high_files)} 个高风险文件。"
            "当前结果基于文件路径、diff 规模、行为关键词和测试覆盖信号生成。"
        ),
        review_focus=focus,
    )

    findings: list[Finding] = []
    for file in (review_targets or high_files[:5]):
        lines = extract_added_lines(file.patch)
        first_line = int(lines[0]["line"]) if lines else 1
        reason_text = "; ".join(file.risk_reasons[:3])

        if any("访问控制" in reason or "权限" in reason for reason in file.risk_reasons):
            findings.append(
                Finding(
                    title="访问控制变更需要人工确认",
                    severity="P1",
                    confidence=0.72,
                    category="security",
                    file=file.filename,
                    line=first_line,
                    evidence=reason_text,
                    impact="权限逻辑的细微变化可能导致生产路径中错误放行或错误拒绝访问。",
                    suggestion="确认默认路径是否为拒绝访问，并补充匿名用户、普通用户和高权限用户的回归测试。",
                    comment_draft=(
                        "这处变更涉及访问控制逻辑。建议确认默认分支是否为拒绝访问，并补充角色/权限相关回归测试。"
                    ),
                )
            )
        elif any("SQL" in reason or "数据库" in reason for reason in file.risk_reasons):
            findings.append(
                Finding(
                    title="数据库行为变更需要补充空值和失败路径覆盖",
                    severity="P2",
                    confidence=0.68,
                    category="logic",
                    file=file.filename,
                    line=first_line,
                    evidence=reason_text,
                    impact="数据库变更可能在空结果、部分写入失败或迁移不兼容时产生问题。",
                    suggestion="补充空结果、写入失败、迁移回滚或兼容性相关测试。",
                    comment_draft="这处数据库相关变更建议补充空状态和失败路径测试。",
                )
            )
        elif "没有修改测试文件" in reason_text:
            findings.append(
                Finding(
                    title="行为变更缺少对应测试更新",
                    severity="P2",
                    confidence=0.74,
                    category="test",
                    file=file.filename,
                    line=first_line,
                    evidence=reason_text,
                    impact="缺少自动化测试时，评审者更难判断该行为后续是否会回归。",
                    suggestion="在相邻模块补充或更新测试，覆盖主要成功路径和失败路径。",
                    comment_draft="我没有看到该行为变更对应的测试更新。建议补充变更路径的测试覆盖。",
                )
            )

    test_suggestions = [
        TestSuggestion(
            title="为最高风险文件补充回归测试",
            reason="风险分类器识别到行为敏感路径或测试缺失信号。",
            suggested_case="覆盖一个成功路径、一个失败路径，以及一个边界值或空输入场景。",
        ),
        TestSuggestion(
            title="使用 dry-run 验证 GitHub 评论预览",
            reason="演示需要证明报告可以转换成适合 PR 讨论的 Markdown。",
            suggested_case="使用 dry_run=true 运行分析，并检查 Markdown 预览是否适合作为 PR 评论。",
        ),
    ]
    return ReviewOutput(
        source="fallback",
        summary=summary,
        findings=findings[:8],
        test_suggestions=test_suggestions,
    )


def _focus_from_reasons(files: list[ChangedFile]) -> list[str]:
    joined = " ".join(" ".join(file.risk_reasons) for file in files).lower()
    focus: list[str] = []
    if "访问控制" in joined or "权限" in joined:
        focus.append("权限校验")
    if "数据库" in joined or "sql" in joined:
        focus.append("数据正确性")
    if "测试" in joined:
        focus.append("测试覆盖")
    if "错误" in joined:
        focus.append("错误处理")
    return focus or ["行为变更", "测试覆盖", "评审证据"]
