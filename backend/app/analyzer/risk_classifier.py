import re

from app.analyzer.diff_parser import extract_added_lines, should_review_file
from app.models.schemas import ChangedFile


HIGH_RISK_PATHS = {
    "auth": "touches authentication or authorization code",
    "permission": "touches permission logic",
    "payment": "touches payment code",
    "migration": "touches database migration code",
    "security": "touches security-sensitive code",
    "crypto": "touches cryptography code",
    "database": "touches database code",
    "config": "changes runtime configuration",
}

RISK_PATTERNS = [
    (re.compile(r"\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b", re.I), "adds SQL or database query logic", 14),
    (re.compile(r"allow|deny|role|admin|token|jwt|session", re.I), "changes access-control related logic", 18),
    (re.compile(r"except\s*:|catch\s*\(|try\s*\{|raise|throw", re.I), "changes error handling behavior", 10),
    (re.compile(r"fetch\(|axios|httpx|requests\.|http\.", re.I), "adds network request behavior", 10),
    (re.compile(r"TODO|FIXME|temporary|hack", re.I), "contains temporary implementation markers", 8),
    (re.compile(r"return\s+true|return\s+None|return\s+null", re.I), "adds permissive or nullable early return", 12),
]


def classify_files(files: list[ChangedFile]) -> list[ChangedFile]:
    total_files = len(files)
    has_test_change = any(_is_test_file(item.filename) for item in files)
    classified: list[ChangedFile] = []

    for item in files:
        score = min(35, item.additions + item.deletions)
        reasons: list[str] = []
        normalized = item.filename.lower().replace("\\", "/")

        if not should_review_file(item.filename, total_files=total_files):
            item.risk_score = 5
            item.risk_level = "low"
            item.risk_reasons = ["low-value generated, binary, or lock file for review"]
            classified.append(item)
            continue

        for token, reason in HIGH_RISK_PATHS.items():
            if token in normalized:
                score += 18
                reasons.append(reason)

        if item.additions + item.deletions >= 120:
            score += 15
            reasons.append("large diff increases review risk")
        elif item.additions + item.deletions >= 40:
            score += 8
            reasons.append("medium-sized behavior change")

        added_text = "\n".join(str(line["content"]) for line in extract_added_lines(item.patch))
        for pattern, reason, weight in RISK_PATTERNS:
            if pattern.search(added_text):
                score += weight
                reasons.append(reason)

        if not has_test_change and not _is_test_file(item.filename):
            score += 12
            reasons.append("no test file changed in this PR")

        if normalized.endswith((".json", ".yml", ".yaml", ".toml")):
            score += 6
            reasons.append("configuration or dependency behavior may change")

        item.risk_score = max(0, min(100, score))
        item.risk_level = _level(item.risk_score)
        item.risk_reasons = _dedupe(reasons) or ["small isolated change"]
        classified.append(item)

    return sorted(classified, key=lambda file: file.risk_score, reverse=True)


def _level(score: int) -> str:
    if score >= 85:
        return "critical"
    if score >= 65:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _is_test_file(filename: str) -> bool:
    path = filename.lower()
    return "test" in path or "spec" in path or path.endswith(("_test.py", ".test.ts", ".spec.ts"))


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
