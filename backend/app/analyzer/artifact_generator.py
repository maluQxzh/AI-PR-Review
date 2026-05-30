import json
import re
from collections import defaultdict
from pathlib import PurePosixPath

import httpx

from app.llm.openai_provider import OpenAICompatibleProvider
from app.models.schemas import (
    ChangedFile,
    ChangelogEntry,
    CodeImprovement,
    DocumentationSuggestion,
    Finding,
    GeneratedArtifacts,
    LabelSuggestion,
    PrDescriptionSuggestion,
    PrInfo,
    PrMetadataSuggestion,
    ReviewContext,
    SimilarItem,
    Summary,
    TestSuggestion,
    WalkthroughItem,
)


VALID_PR_TYPES = {
    "feature",
    "bugfix",
    "refactor",
    "docs",
    "test",
    "chore",
    "security",
    "performance",
}


async def generate_artifacts(
    pr: PrInfo,
    files: list[ChangedFile],
    summary: Summary,
    findings: list[Finding],
    test_suggestions: list[TestSuggestion],
    review_context: ReviewContext | None,
    mode: str,
) -> GeneratedArtifacts:
    fallback = build_fallback_artifacts(
        pr, files, summary, findings, test_suggestions, review_context
    )
    provider = OpenAICompatibleProvider()
    if not provider.settings.llm_api_key:
        return fallback

    try:
        payload = _build_llm_payload(pr, files, summary, findings, test_suggestions, review_context, mode)
        async with httpx.AsyncClient(timeout=provider.settings.llm_retry_timeout_seconds) as client:
            response = await client.post(
                f"{provider.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {provider.settings.llm_api_key}"},
                json=payload,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return coerce_generated_artifacts(json.loads(content), fallback)
    except Exception:
        return fallback


def coerce_generated_artifacts(payload: dict, fallback: GeneratedArtifacts) -> GeneratedArtifacts:
    if not isinstance(payload, dict):
        return fallback

    metadata = payload.get("pr_metadata") if isinstance(payload.get("pr_metadata"), dict) else {}
    pr_type = str(metadata.get("pr_type") or fallback.pr_metadata.pr_type).lower()
    if pr_type not in VALID_PR_TYPES:
        pr_type = fallback.pr_metadata.pr_type

    labels = [
        LabelSuggestion(
            name=str(item.get("name") or "").strip()[:60],
            reason=str(item.get("reason") or "Derived from PR analysis.").strip(),
            confidence=_confidence(item.get("confidence"), 0.7),
        )
        for item in _list(metadata.get("labels"))
        if str(item.get("name") or "").strip()
    ] or fallback.pr_metadata.labels

    description = payload.get("pr_description") if isinstance(payload.get("pr_description"), dict) else {}
    walkthrough = [
        WalkthroughItem(
            area=str(item.get("area") or "Changes").strip(),
            files=[str(path) for path in _list(item.get("files")) if str(path)],
            description=str(item.get("description") or "").strip(),
        )
        for item in _list(description.get("walkthrough"))
        if str(item.get("description") or "").strip()
    ] or fallback.pr_description.walkthrough

    artifacts = GeneratedArtifacts(
        pr_metadata=PrMetadataSuggestion(
            suggested_title=str(
                metadata.get("suggested_title") or fallback.pr_metadata.suggested_title
            ).strip(),
            pr_type=pr_type,  # type: ignore[arg-type]
            labels=labels[:8],
        ),
        pr_description=PrDescriptionSuggestion(
            summary=str(description.get("summary") or fallback.pr_description.summary).strip(),
            walkthrough=walkthrough[:8],
            testing=[
                str(item).strip()
                for item in _list(description.get("testing"))
                if str(item).strip()
            ][:8]
            or fallback.pr_description.testing,
            risks=[
                str(item).strip()
                for item in _list(description.get("risks"))
                if str(item).strip()
            ][:8]
            or fallback.pr_description.risks,
            rollback=(
                str(description.get("rollback")).strip()
                if description.get("rollback") is not None
                else fallback.pr_description.rollback
            ),
            markdown=str(description.get("markdown") or "").strip(),
        ),
        code_improvements=[
            CodeImprovement(
                title=str(item.get("title") or "Code improvement").strip(),
                file=str(item.get("file") or "").strip(),
                line=_optional_int(item.get("line")),
                category=str(item.get("category") or "maintainability").strip(),
                reason=str(item.get("reason") or "").strip(),
                suggestion=str(item.get("suggestion") or "").strip(),
                confidence=_confidence(item.get("confidence"), 0.65),
            )
            for item in _list(payload.get("code_improvements"))
            if str(item.get("file") or "").strip()
            and str(item.get("suggestion") or "").strip()
        ][:8]
        or fallback.code_improvements,
        documentation_suggestions=[
            DocumentationSuggestion(
                target=str(item.get("target") or "README.md").strip(),
                reason=str(item.get("reason") or "").strip(),
                proposed_text=str(item.get("proposed_text") or "").strip(),
            )
            for item in _list(payload.get("documentation_suggestions"))
            if str(item.get("proposed_text") or "").strip()
        ][:5]
        or fallback.documentation_suggestions,
        changelog=_coerce_changelog(payload.get("changelog"), fallback.changelog),
        similar_items=[
            SimilarItem(
                title=str(item.get("title") or "").strip(),
                html_url=str(item.get("html_url") or "").strip(),
                state=str(item.get("state") or "open").strip(),
                kind=(
                    "pull_request"
                    if str(item.get("kind") or "").strip() == "pull_request"
                    else "issue"
                ),
                matched_terms=[
                    str(term).strip()
                    for term in _list(item.get("matched_terms"))
                    if str(term).strip()
                ][:8],
                relevance_reason=str(item.get("relevance_reason") or "").strip(),
            )
            for item in _list(payload.get("similar_items"))
            if str(item.get("title") or "").strip() and str(item.get("html_url") or "").strip()
        ][:8]
        or fallback.similar_items,
    )
    if not artifacts.pr_description.markdown:
        artifacts.pr_description.markdown = build_pr_description_markdown(artifacts)
    return artifacts


def build_fallback_artifacts(
    pr: PrInfo,
    files: list[ChangedFile],
    summary: Summary,
    findings: list[Finding],
    test_suggestions: list[TestSuggestion],
    review_context: ReviewContext | None,
) -> GeneratedArtifacts:
    pr_type = _infer_pr_type(pr, files, findings)
    labels = _infer_labels(pr_type, files, findings, test_suggestions)
    walkthrough = _build_walkthrough(files)
    risks = [finding.title for finding in findings[:5]] or [summary.risk_overview]
    testing = [item.suggested_case for item in test_suggestions[:5]] or ["Run the existing test suite."]
    improvements = _build_code_improvements(files, findings)
    docs = _build_documentation_suggestions(pr, files)
    similar_items = _build_similar_items(pr, files, review_context)
    changelog = ChangelogEntry(
        category=pr_type,
        entry=f"{_changelog_prefix(pr_type)} {summary.what_changed.rstrip('。.')}",
    )
    artifacts = GeneratedArtifacts(
        pr_metadata=PrMetadataSuggestion(
            suggested_title=_suggested_title(pr, pr_type),
            pr_type=pr_type,  # type: ignore[arg-type]
            labels=labels,
        ),
        pr_description=PrDescriptionSuggestion(
            summary=summary.what_changed,
            walkthrough=walkthrough,
            testing=testing,
            risks=risks,
            rollback="Revert this PR if the changed behavior causes regressions in the touched paths.",
        ),
        code_improvements=improvements,
        documentation_suggestions=docs,
        changelog=changelog,
        similar_items=similar_items,
    )
    artifacts.pr_description.markdown = build_pr_description_markdown(artifacts)
    return artifacts


def build_pr_description_markdown(artifacts: GeneratedArtifacts) -> str:
    description = artifacts.pr_description
    walkthrough = "\n".join(
        f"- **{item.area}**: {item.description} (`{', '.join(item.files[:4])}`)"
        for item in description.walkthrough
    )
    testing = "\n".join(f"- {item}" for item in description.testing)
    risks = "\n".join(f"- {item}" for item in description.risks)
    labels = ", ".join(label.name for label in artifacts.pr_metadata.labels)
    changelog = artifacts.changelog.entry if artifacts.changelog else "N/A"
    return "\n".join(
        [
            "## Summary",
            description.summary,
            "",
            "## Walkthrough",
            walkthrough or "- No changed files were available.",
            "",
            "## Testing",
            testing or "- Not run.",
            "",
            "## Risks / Rollback",
            risks or "- No specific risks identified.",
            f"- Rollback: {description.rollback or 'Revert the PR if needed.'}",
            "",
            "## Review Notes",
            f"- Suggested type: `{artifacts.pr_metadata.pr_type}`",
            f"- Suggested labels: {labels or 'none'}",
            f"- Changelog: {changelog}",
        ]
    )


def build_artifacts_markdown(artifacts: GeneratedArtifacts) -> str:
    labels = "\n".join(
        f"- `{item.name}` ({item.confidence:.0%}): {item.reason}"
        for item in artifacts.pr_metadata.labels
    )
    walkthrough = "\n".join(
        f"- **{item.area}**: {item.description} ({', '.join(item.files[:5])})"
        for item in artifacts.pr_description.walkthrough
    )
    improvements = "\n".join(
        f"- **{item.title}** (`{item.file}{f':{item.line}' if item.line else ''}`): {item.suggestion}"
        for item in artifacts.code_improvements[:6]
    )
    docs = "\n".join(
        f"- **{item.target}**: {item.reason}\n  - {item.proposed_text}"
        for item in artifacts.documentation_suggestions[:4]
    )
    similar = "\n".join(
        f"- [{item.title}]({item.html_url}) ({item.kind}, {item.state}): {item.relevance_reason}"
        for item in artifacts.similar_items[:6]
    )
    return "\n".join(
        [
            "## PR Preparation",
            "",
            f"- Suggested title: {artifacts.pr_metadata.suggested_title}",
            f"- Suggested type: `{artifacts.pr_metadata.pr_type}`",
            "",
            "### Labels",
            labels or "- No label suggestions.",
            "",
            "### Walkthrough",
            walkthrough or "- No walkthrough available.",
            "",
            "### Changelog",
            artifacts.changelog.entry if artifacts.changelog else "- No changelog suggestion.",
            "",
            "### Code Improvements",
            improvements or "- No non-blocking improvements suggested.",
            "",
            "### Documentation",
            docs or "- No documentation updates suggested.",
            "",
            "### Similar Issues / PRs",
            similar or "- No similar items found.",
            "",
            "### Suggested PR Description",
            "",
            artifacts.pr_description.markdown,
        ]
    )


def _build_llm_payload(
    pr: PrInfo,
    files: list[ChangedFile],
    summary: Summary,
    findings: list[Finding],
    test_suggestions: list[TestSuggestion],
    review_context: ReviewContext | None,
    mode: str,
) -> dict:
    compact_files = [
        {
            "filename": item.filename,
            "status": item.status,
            "additions": item.additions,
            "deletions": item.deletions,
            "risk_level": item.risk_level,
            "risk_score": item.risk_score,
            "risk_dimensions": item.risk_dimensions,
            "risk_reasons": item.risk_reasons,
            "patch": (item.patch or "")[:5000],
        }
        for item in files[:15]
    ]
    context_history = review_context.history if review_context else []
    return {
        "model": OpenAICompatibleProvider().model_for_mode(mode),
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate non-mutating GitHub PR preparation artifacts. "
                    "Return strict JSON only. Do not invent links or claim writes were made. "
                    "Separate non-blocking code improvements from review findings."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "pr": pr.model_dump(),
                        "summary": summary.model_dump(),
                        "files": compact_files,
                        "findings": [item.model_dump(exclude={"tag"}) for item in findings[:8]],
                        "test_suggestions": [item.model_dump() for item in test_suggestions[:8]],
                        "history": context_history[:8],
                        "schema": "generated_artifacts object from the API plan",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }


def _infer_pr_type(pr: PrInfo, files: list[ChangedFile], findings: list[Finding]) -> str:
    text = " ".join(
        [
            pr.title,
            pr.description or "",
            " ".join(commit.get("message", "") for commit in pr.commits),
            " ".join(file.filename for file in files),
        ]
    ).lower()
    dimensions = {dim for file in files for dim in file.risk_dimensions}
    if "security" in dimensions or any(finding.category == "security" for finding in findings):
        return "security"
    if "performance" in dimensions:
        return "performance"
    if re.search(r"\b(fix|bug|hotfix|regression|修复)\b", text):
        return "bugfix"
    if files and all(_is_doc_file(file.filename) for file in files):
        return "docs"
    if files and all(_is_test_file(file.filename) for file in files):
        return "test"
    if re.search(r"\b(refactor|cleanup|重构)\b", text):
        return "refactor"
    if re.search(r"\b(chore|build|ci|deps)\b", text):
        return "chore"
    return "feature"


def _infer_labels(
    pr_type: str,
    files: list[ChangedFile],
    findings: list[Finding],
    test_suggestions: list[TestSuggestion],
) -> list[LabelSuggestion]:
    labels: list[LabelSuggestion] = [
        LabelSuggestion(name=f"type:{pr_type}", reason="Derived from PR title, files, and risk dimensions.", confidence=0.78)
    ]
    high_count = sum(1 for file in files if file.risk_level in {"critical", "high"})
    if high_count:
        labels.append(LabelSuggestion(name="risk:high", reason=f"{high_count} high-risk file(s) were detected.", confidence=0.84))
    if any(finding.category == "security" for finding in findings):
        labels.append(LabelSuggestion(name="area:security", reason="Security findings or dimensions were detected.", confidence=0.82))
    if any("test_gap" in file.risk_dimensions for file in files) or test_suggestions:
        labels.append(LabelSuggestion(name="needs-tests", reason="The review produced testing suggestions.", confidence=0.74))
    if any(_is_doc_file(file.filename) for file in files):
        labels.append(LabelSuggestion(name="area:docs", reason="Documentation files changed.", confidence=0.7))
    if any(_is_frontend_file(file.filename) for file in files):
        labels.append(LabelSuggestion(name="area:frontend", reason="Frontend files changed.", confidence=0.68))
    if any(_is_backend_file(file.filename) for file in files):
        labels.append(LabelSuggestion(name="area:backend", reason="Backend or API files changed.", confidence=0.68))
    return labels[:8]


def _build_walkthrough(files: list[ChangedFile]) -> list[WalkthroughItem]:
    groups: dict[str, list[ChangedFile]] = defaultdict(list)
    for file in files:
        path = PurePosixPath(file.filename)
        area = path.parts[0] if len(path.parts) > 1 else path.suffix.lstrip(".") or "root"
        groups[area].append(file)
    return [
        WalkthroughItem(
            area=area,
            files=[file.filename for file in grouped[:8]],
            description=(
                f"Updates {len(grouped)} file(s) with "
                f"{sum(file.additions for file in grouped)} additions and "
                f"{sum(file.deletions for file in grouped)} deletions."
            ),
        )
        for area, grouped in list(groups.items())[:8]
    ]


def _build_code_improvements(files: list[ChangedFile], findings: list[Finding]) -> list[CodeImprovement]:
    finding_keys = {(item.file, item.line) for item in findings}
    improvements: list[CodeImprovement] = []
    for file in files:
        line = _first_added_line(file.patch)
        if (file.filename, line or 0) in finding_keys:
            continue
        if "maintainability" in file.risk_dimensions:
            improvements.append(
                CodeImprovement(
                    title="Simplify the touched path",
                    file=file.filename,
                    line=line,
                    category="maintainability",
                    reason="The file was flagged for maintainability review.",
                    suggestion="Consider extracting repeated logic or naming the key branch conditions before merge.",
                    confidence=0.62,
                )
            )
        elif "test_gap" in file.risk_dimensions:
            improvements.append(
                CodeImprovement(
                    title="Make the changed behavior easier to verify",
                    file=file.filename,
                    line=line,
                    category="testability",
                    reason="Risk analysis found a behavior change without nearby test coverage.",
                    suggestion="Add a focused test around the main changed branch and a failure path.",
                    confidence=0.7,
                )
            )
        elif file.risk_score >= 60:
            improvements.append(
                CodeImprovement(
                    title="Add reviewer-facing notes for this high-risk change",
                    file=file.filename,
                    line=line,
                    category="reviewability",
                    reason="The file has elevated risk even if no verified finding was produced.",
                    suggestion="Mention the intended behavior and validation path in the PR description.",
                    confidence=0.64,
                )
            )
    return improvements[:6]


def _build_documentation_suggestions(pr: PrInfo, files: list[ChangedFile]) -> list[DocumentationSuggestion]:
    if any(_is_doc_file(file.filename) for file in files):
        return []
    if not files:
        return []
    target = "README.md"
    if any("api" in file.filename.lower() or "route" in file.filename.lower() for file in files):
        target = "docs/api.md"
    return [
        DocumentationSuggestion(
            target=target,
            reason="The PR changes behavior but does not include a documentation update.",
            proposed_text=(
                f"Document the behavior introduced by {pr.owner}/{pr.repo}#{pr.number}, "
                "including inputs, expected outputs, and any reviewer-noted risks."
            ),
        )
    ]


def _build_similar_items(
    pr: PrInfo,
    files: list[ChangedFile],
    review_context: ReviewContext | None,
) -> list[SimilarItem]:
    if not review_context:
        return []
    terms = _history_terms(pr, files)
    items: list[SimilarItem] = []
    for item in review_context.history[:8]:
        title = str(item.get("title") or "").strip()
        url = str(item.get("html_url") or "").strip()
        if not title or not url:
            continue
        matched = [term for term in terms if term.lower() in title.lower()]
        items.append(
            SimilarItem(
                title=title,
                html_url=url,
                state=str(item.get("state") or "open"),
                kind="pull_request" if item.get("kind") == "pull_request" else "issue",
                matched_terms=matched[:8],
                relevance_reason=(
                    "Matched by PR title/path keywords collected during repository history search."
                    if matched
                    else "Returned by repository history search for this PR context."
                ),
            )
        )
    return items


def _suggested_title(pr: PrInfo, pr_type: str) -> str:
    title = pr.title.strip()
    prefix = f"{pr_type}: "
    if title.lower().startswith(prefix):
        return title
    return f"{prefix}{title[:90]}"


def _history_terms(pr: PrInfo, files: list[ChangedFile]) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_-]{3,}", pr.title or "")
    for file in files[:5]:
        path = PurePosixPath(file.filename)
        terms.extend([path.stem, *(part for part in path.parts[:-1] if len(part) >= 3)])
    result: list[str] = []
    for term in terms:
        if term not in result:
            result.append(term)
    return result[:8]


def _changelog_prefix(pr_type: str) -> str:
    return {
        "bugfix": "Fixed:",
        "security": "Security:",
        "performance": "Improved:",
        "docs": "Docs:",
        "test": "Tests:",
        "refactor": "Changed:",
        "chore": "Chore:",
    }.get(pr_type, "Added:")


def _coerce_changelog(payload: object, fallback: ChangelogEntry | None) -> ChangelogEntry | None:
    if not isinstance(payload, dict):
        return fallback
    entry = str(payload.get("entry") or "").strip()
    if not entry:
        return fallback
    return ChangelogEntry(category=str(payload.get("category") or "changed"), entry=entry)


def _first_added_line(patch: str | None) -> int | None:
    if not patch:
        return None
    current = None
    for line in patch.splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            current = int(match.group(1)) if match else None
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            return current
        if not line.startswith("-"):
            current += 1
    return None


def _confidence(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _optional_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _is_doc_file(path: str) -> bool:
    lower = path.lower()
    return lower.endswith((".md", ".rst", ".txt")) or lower.startswith("docs/")


def _is_test_file(path: str) -> bool:
    lower = path.lower()
    return "/test/" in f"/{lower}" or "/tests/" in f"/{lower}" or lower.endswith(
        ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".test.js", ".spec.js")
    )


def _is_frontend_file(path: str) -> bool:
    lower = path.lower()
    return lower.startswith("frontend/") or lower.endswith((".tsx", ".jsx", ".css"))


def _is_backend_file(path: str) -> bool:
    lower = path.lower()
    return lower.startswith("backend/") or lower.endswith((".py", ".go", ".rs", ".java"))
