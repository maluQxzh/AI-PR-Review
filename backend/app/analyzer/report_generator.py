from app.analyzer.artifact_generator import build_artifacts_markdown
from app.models.schemas import ChangedFile, Finding, GeneratedArtifacts, PrInfo, Summary, TestSuggestion


def build_github_comment(
    pr: PrInfo,
    summary: Summary,
    files: list[ChangedFile],
    findings: list[Finding],
    test_suggestions: list[TestSuggestion],
    generated_artifacts: GeneratedArtifacts | None = None,
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
    artifact_lines = ""
    if generated_artifacts:
        label_names = ", ".join(label.name for label in generated_artifacts.pr_metadata.labels)
        walkthrough = "\n".join(
            f"- **{item.area}**: {item.description}" for item in generated_artifacts.pr_description.walkthrough[:5]
        )
        changelog = generated_artifacts.changelog.entry if generated_artifacts.changelog else "暂无 changelog 建议。"
        artifact_lines = "\n".join(
            [
                "",
                "### PR 准备建议",
                f"- 建议标题：{generated_artifacts.pr_metadata.suggested_title}",
                f"- 类型：`{generated_artifacts.pr_metadata.pr_type}`",
                f"- Labels：{label_names or '暂无'}",
                "",
                "### Walkthrough",
                walkthrough or "- 暂无 walkthrough。",
                "",
                "### Changelog",
                changelog,
            ]
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
            artifact_lines,
            "",
            "_由 AI PR Review demo 生成，发布前请人工确认。_",
        ]
    )


def build_comment_by_type(
    base_markdown: str,
    generated_artifacts: GeneratedArtifacts | dict | None,
    comment_type: str,
) -> str:
    if comment_type != "artifacts":
        return base_markdown
    if not generated_artifacts:
        return "_PR preparation artifacts are not ready yet._"
    if isinstance(generated_artifacts, dict):
        generated_artifacts = GeneratedArtifacts.model_validate(generated_artifacts)
    return build_artifacts_markdown(generated_artifacts)
