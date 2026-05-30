from app.analyzer.diff_parser import extract_added_lines
from app.llm.base import ReviewOutput
from app.llm.openai_provider import OpenAICompatibleProvider
from app.models.schemas import ChangedFile, Finding, PrInfo, Summary, TestSuggestion


async def review_pr(pr: PrInfo, files: list[ChangedFile], mode: str) -> ReviewOutput:
    provider = OpenAICompatibleProvider()
    top_n = 0 if mode == "fast" else (15 if mode == "deep" else 5)
    review_targets = files[:top_n] if top_n else []

    try:
        output = await provider.review(pr, review_targets or files[:5], mode)
        if output:
            return output
    except Exception:
        # Demo fallback: keep the report useful when LLM credentials/network are unavailable.
        pass

    return _heuristic_review(pr, files, review_targets)


def _heuristic_review(pr: PrInfo, files: list[ChangedFile], review_targets: list[ChangedFile]) -> ReviewOutput:
    high_files = [file for file in files if file.risk_level in {"high", "critical"}]
    focus = _focus_from_reasons(files)
    summary = Summary(
        what_changed=(
            f"PR #{pr.number} changes {len(files)} file(s), led by "
            f"{', '.join(file.filename for file in files[:3]) or 'no files'}."
        ),
        risk_overview=(
            f"{len(high_files)} high-risk file(s) were identified. "
            "The fallback analyzer used path, diff size, behavior keywords, and test coverage signals."
        ),
        review_focus=focus,
    )

    findings: list[Finding] = []
    for file in (review_targets or high_files[:5]):
        lines = extract_added_lines(file.patch)
        first_line = int(lines[0]["line"]) if lines else 1
        reason_text = "; ".join(file.risk_reasons[:3])

        if any("access-control" in reason or "permission" in reason for reason in file.risk_reasons):
            findings.append(
                Finding(
                    title="Access-control change needs reviewer confirmation",
                    severity="P1",
                    confidence=0.72,
                    category="security",
                    file=file.filename,
                    line=first_line,
                    evidence=reason_text,
                    impact="A subtle permission change can grant or deny access in production paths.",
                    suggestion="Verify deny-by-default behavior and add tests for anonymous, normal, and privileged users.",
                    comment_draft=(
                        "This change touches access-control logic. Please confirm the default path is deny-by-default "
                        "and add role/permission regression tests."
                    ),
                )
            )
        elif any("SQL" in reason or "database" in reason for reason in file.risk_reasons):
            findings.append(
                Finding(
                    title="Database behavior change may need null and rollback coverage",
                    severity="P2",
                    confidence=0.68,
                    category="logic",
                    file=file.filename,
                    line=first_line,
                    evidence=reason_text,
                    impact="Database changes can fail on empty results, partial writes, or incompatible migrations.",
                    suggestion="Add coverage for empty result sets, failed writes, and migration rollback or compatibility.",
                    comment_draft="This database-related change would benefit from explicit empty-state and failure-path tests.",
                )
            )
        elif "no test file changed" in reason_text:
            findings.append(
                Finding(
                    title="Behavior change has no matching test update",
                    severity="P2",
                    confidence=0.74,
                    category="test",
                    file=file.filename,
                    line=first_line,
                    evidence=reason_text,
                    impact="Reviewers have less protection against regressions in the changed behavior.",
                    suggestion="Add or update tests near the changed module that cover the main success and failure paths.",
                    comment_draft="I do not see a matching test change for this behavior. Could we add coverage for the changed path?",
                )
            )

    test_suggestions = [
        TestSuggestion(
            title="Add regression tests for the highest-risk changed file",
            reason="The risk classifier found behavior-sensitive paths or a missing test update.",
            suggested_case="Cover one success path, one failure path, and one boundary/empty-input path.",
        ),
        TestSuggestion(
            title="Exercise generated GitHub comment as dry-run",
            reason="The demo should prove the report can be converted into PR-reviewable Markdown.",
            suggested_case="Run analysis with dry_run=true and paste the Markdown preview into a sample PR discussion.",
        ),
    ]
    return ReviewOutput(summary=summary, findings=findings[:8], test_suggestions=test_suggestions)


def _focus_from_reasons(files: list[ChangedFile]) -> list[str]:
    joined = " ".join(" ".join(file.risk_reasons) for file in files).lower()
    focus: list[str] = []
    if "access-control" in joined or "permission" in joined:
        focus.append("permissions")
    if "database" in joined or "sql" in joined:
        focus.append("data correctness")
    if "test" in joined:
        focus.append("test coverage")
    if "error" in joined:
        focus.append("error handling")
    return focus or ["changed behavior", "test coverage", "review evidence"]
