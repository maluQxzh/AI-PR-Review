from app.models.schemas import ChangedFile, Finding


def verify_findings(findings: list[Finding], files: list[ChangedFile]) -> list[Finding]:
    changed_files = {file.filename for file in files}
    seen: set[tuple[str, int, str]] = set()
    verified: list[Finding] = []

    for finding in findings:
        key = (finding.file, finding.line, finding.title.lower().strip())
        if key in seen:
            continue
        if finding.file not in changed_files:
            continue
        if finding.line <= 0:
            continue
        if finding.confidence < 0.55:
            continue
        if len(finding.evidence.strip()) < 8 or len(finding.suggestion.strip()) < 8:
            continue
        if _is_style_only(finding):
            continue
        seen.add(key)
        verified.append(finding)

    return verified


def _is_style_only(finding: Finding) -> bool:
    text = f"{finding.title} {finding.evidence} {finding.suggestion}".lower()
    style_words = ["formatting", "naming", "indent", "whitespace", "prefer"]
    risk_words = ["security", "permission", "test", "data", "error", "null", "logic", "impact"]
    return any(word in text for word in style_words) and not any(word in text for word in risk_words)
