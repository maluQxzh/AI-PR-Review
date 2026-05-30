from app.models.schemas import ChangedFile, Finding, PrInfo, Summary, TestSuggestion


def build_github_comment(
    pr: PrInfo,
    summary: Summary,
    files: list[ChangedFile],
    findings: list[Finding],
    test_suggestions: list[TestSuggestion],
) -> str:
    risk_lines = "\n".join(
        f"- `{file.filename}`: {file.risk_level} ({file.risk_score}) - {', '.join(file.risk_reasons[:2])}"
        for file in files[:5]
    )
    finding_lines = "\n".join(
        (
            f"- **{finding.severity} {finding.tag or '[问题]'} {finding.title}** "
            f"(`{finding.file}:{finding.line}`，置信度 {finding.confidence:.0%})\n"
            f"  - 影响：{finding.impact}\n"
            f"  - 建议：{finding.suggestion}"
        )
        for finding in findings[:8]
    )
    test_lines = "\n".join(
        f"- **{item.title}**: {item.suggested_case}" for item in test_suggestions[:5]
    )

    return "\n".join(
        [
            "## AI PR Review Summary",
            "",
            f"PR: {pr.owner}/{pr.repo}#{pr.number} - {pr.title}",
            "",
            "### 变更内容",
            summary.what_changed,
            "",
            "### 风险概览",
            summary.risk_overview,
            "",
            "### 评审重点",
            ", ".join(summary.review_focus),
            "",
            "### 高风险文件",
            risk_lines or "- 未发现明显高风险文件。",
            "",
            "### 发现的问题",
            finding_lines or "- 校验后没有发现有明确证据的问题。",
            "",
            "### 测试建议",
            test_lines or "- 暂无额外测试建议。",
            "",
            "_由 AI PR Review demo 生成，发布前请人工确认。_",
        ]
    )
