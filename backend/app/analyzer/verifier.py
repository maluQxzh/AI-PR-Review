import re
from pathlib import Path

from app.analyzer.diff_parser import IGNORE_PATTERNS, extract_added_lines, should_review_file
from app.analyzer.risk_classifier import is_test_file
from app.models.schemas import ChangedFile, Finding

# ---------------------------------------------------------------------------
# Stop words filtered out during evidence–diff cross-referencing
# ---------------------------------------------------------------------------
_STOP_WORDS: set[str] = {
    "the", "and", "that", "this", "with", "from", "your", "have",
    "will", "should", "would", "could", "about", "code", "here",
    "change", "when", "what", "where", "which", "their", "there",
    "been", "into", "more", "some", "such", "than", "then", "they",
    "very", "just", "over", "also", "after", "before", "being",
    "does", "each", "else", "like", "make", "only", "other",
    "these", "those", "well", "part", "line", "file", "added",
    "modified", "因为", "所以", "但是", "或者", "而且", "然后",
    "这个", "那个", "这些", "那些", "一个", "什么", "哪里",
    "可以", "需要", "应该", "可能", "已经", "没有", "修改",
    "增加", "删除", "代码", "文件", "表示", "用于",
}

# ---------------------------------------------------------------------------
# Expanded style-only detection
# ---------------------------------------------------------------------------
_STYLE_KEYWORDS: list[str] = [
    # Naming
    "naming convention", "variable name", "function name", "class name",
    "rename", "naming", "camelcase", "snake_case", "pascalcase",
    "命名规范", "命名", "变量名", "函数名", "类名", "重命名",
    # Formatting
    "formatting", "indentation", "indent", "whitespace", "spacing",
    "line length", "trailing whitespace", "trailing space", "newline",
    "missing space", "extra space", "tab", "tabs",
    "格式化", "缩进", "空格", "空行", "行长度",
    # Import / style-tool
    "eslint", "prettier", "stylelint", "pycodestyle", "flake8", "pylint",
    "import order", "unused import", "sort imports", "organize imports",
    # Syntax trivia
    "semicolon", "trailing comma", "comma-dangle", "quote style",
    "double quote", "single quote", "prefer const", "prefer let",
    "arrow function", "分号", "引号",
    # Documentation
    "docstring", "comment style", "missing comment", "add comment",
    "typo", "spelling", "misspelling",
    "注释", "文档", "拼写", "错别字",
    # Code style
    "brace style", "bracket style", "curly brace", "parentheses style",
    "code style", "lint", "linter", "prefer",
    "代码风格", "花括号", "括号",
]

_RISK_EXCLUSIONS: list[str] = [
    "security", "permission", "auth", "injection", "xss", "csrf",
    "test", "coverage", "assert", "mock",
    "data", "database", "sql", "query",
    "error", "exception", "crash", "fail", "失败", "错误", "异常",
    "null", "undefined", "none", "empty", "missing", "空", "缺失",
    "logic", "race condition", "deadlock", "concurrent", "逻辑",
    "impact", "attack", "vulnerability", "exploit", "漏洞", "攻击",
    "memory", "leak", "overflow", "buffer", "内存", "泄漏",
    "password", "token", "secret", "credential", "key", "密码", "令牌", "密钥",
    "validation", "sanitize", "escape", "deserialize", "校验", "验证",
    "安全", "权限", "注入",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_added_line_map(files: list[ChangedFile]) -> dict[str, set[int]]:
    """Return a mapping of filename → set of added line numbers from each diff."""
    result: dict[str, set[int]] = {}
    for file in files:
        lines = extract_added_lines(file.patch)
        # Normalize path separators for consistent lookups
        key = file.filename.replace("\\", "/")
        result[key] = {entry["line"] for entry in lines} if lines else set()
    return result


def _evidence_matches_diff(finding: Finding, added_lines: list[dict]) -> bool:
    """Check whether substantive words from the evidence appear in nearby added lines."""
    if not added_lines:
        # No diff data — cannot disprove; accept the finding.
        return True

    # Extract substantive tokens from evidence + suggestion
    text = f"{finding.evidence} {finding.suggestion}"
    tokens = re.findall(r"[\w一-鿿]{4,}", text.lower())
    meaningful = [t for t in tokens if t not in _STOP_WORDS]
    if not meaningful:
        # No extractable keywords — accept rather than reject.
        return True

    # Only consider added lines within ±5 lines of the reported line
    nearby = [
        entry["content"].lower()
        for entry in added_lines
        if abs(entry["line"] - finding.line) <= 5
    ]
    if not nearby:
        # No nearby added lines — the finding line itself may be context; accept.
        return True

    combined = " ".join(nearby)
    return any(token in combined for token in meaningful)


def _title_similarity(a: str, b: str) -> float:
    """Jaccard similarity over character trigrams (works for Chinese + English)."""
    def trigrams(s: str) -> set[str]:
        s = s.lower().strip()
        return {s[i : i + 3] for i in range(max(len(s) - 2, 0))}

    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _deduplicate_similar(findings: list[Finding]) -> list[Finding]:
    """Remove findings with highly similar titles within the same (file, category) group."""
    if len(findings) <= 1:
        return findings

    # Group by (file, category)
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        key = (f.file.replace("\\", "/"), f.category)
        groups.setdefault(key, []).append(f)

    result: list[Finding] = []
    for items in groups.values():
        if len(items) == 1:
            result.extend(items)
            continue
        # Pairwise dedup: keep higher confidence
        kept: list[Finding] = []
        for candidate in items:
            is_dup = False
            for i, existing in enumerate(kept):
                if _title_similarity(candidate.title, existing.title) >= 0.75:
                    # Keep the higher-confidence one
                    if candidate.confidence > existing.confidence:
                        kept[i] = candidate
                    is_dup = True
                    break
            if not is_dup:
                kept.append(candidate)
        result.extend(kept)

    return result


def _is_style_only(finding: Finding) -> bool:
    """Return True when the finding appears to be about style/formatting only."""
    text = f"{finding.title} {finding.evidence} {finding.suggestion}".lower()
    has_style = any(word in text for word in _STYLE_KEYWORDS)
    has_risk = any(word in text for word in _RISK_EXCLUSIONS)
    return has_style and not has_risk


def _apply_severity_downgrade(finding: Finding, file_obj: ChangedFile | None) -> None:
    """Mutate finding severity and tag based on file-level context.

    Checks are evaluated in priority order; the first match wins.
    """
    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    reverse_order = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}

    def _downgrade_one(current: str) -> str:
        level = severity_order.get(current, 2)
        return reverse_order.get(min(level + 1, 3), "P3")

    if file_obj is None:
        return

    filename = file_obj.filename.replace("\\", "/")

    # 1. File would be excluded by the review filter (lock files, build artifacts, etc.)
    if not should_review_file(filename, total_files=2):
        finding.severity = _downgrade_one(finding.severity)
        finding.tag = "[建议]"
        return

    # 2. Removed file — findings about deleted code have low relevance
    if file_obj.status == "removed":
        finding.severity = "P3"
        finding.tag = "[建议]"
        return

    # 3. Documentation / markdown files
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".txt", ".rst", ".adoc", ".mdx"}:
        finding.severity = "P3"
        finding.tag = "[建议]"
        return

    # 4. Tiny change (≤10 total lines added + deleted)
    if file_obj.additions + file_obj.deletions <= 10:
        finding.severity = _downgrade_one(finding.severity)
        finding.tag = "[建议]"
        return

    # 5. Low-confidence P0 / P1
    if finding.severity in ("P0", "P1") and finding.confidence < 0.65:
        finding.severity = "P2"
        finding.tag = "[建议]"
        return


def _build_source_test_map(files: list[ChangedFile]) -> dict[str, bool]:
    """Return a mapping of source filename → whether a corresponding test file was changed.

    Uses common naming conventions to guess which test file pairs with which source file.
    """
    changed: set[str] = {f.filename.replace("\\", "/") for f in files}
    test_files: set[str] = {p for p in changed if is_test_file(p)}
    source_files: set[str] = {p for p in changed if not is_test_file(p)}
    result: dict[str, bool] = {}

    for src in source_files:
        p = Path(src.replace("\\", "/"))
        stem = p.stem  # filename without extension
        parent = p.parent

        candidates: list[str] = [
            # Python-like
            str(parent / f"test_{stem}.py"),
            str(parent / f"test{stem}.py"),
            str(Path("tests") / parent / f"test_{stem}.py"),
            str(Path("tests") / f"test_{stem}.py"),
            str(Path("tests") / parent / f"{stem}_test.py"),
            str(Path("__tests__") / parent / f"{stem}.test.ts"),
            str(Path("__tests__") / f"{stem}.test.ts"),
            # Jest / JS-like (colocated)
            str(parent / f"{stem}.test.ts"),
            str(parent / f"{stem}.spec.ts"),
            str(parent / f"{stem}.test.js"),
            str(parent / f"{stem}.spec.js"),
            # Jest with __tests__ subdirectory
            str(parent / "__tests__" / f"{stem}.test.ts"),
            str(parent / "__tests__" / f"{stem}.spec.ts"),
            str(parent / "__tests__" / f"{stem}.test.js"),
            # Go-like
            str(parent / f"{stem}_test.go"),
            # Rust-like (typically in tests/ or src/ with #[cfg(test)])
            str(Path("tests") / f"{stem}.rs"),
            str(Path("tests") / f"test_{stem}.rs"),
            str(parent / f"{stem}_test.rs"),
        ]
        # Also check with __tests__ at root adjacent to parent
        for part_idx in range(len(parent.parts)):
            tests_parent = Path("tests").joinpath(*parent.parts[part_idx:])
            candidates.append(str(tests_parent / f"test_{stem}.py"))
            candidates.append(str(tests_parent / f"{stem}_test.py"))
            candidates.append(str(tests_parent / f"{stem}.test.ts"))
            candidates.append(str(tests_parent / f"{stem}.spec.ts"))

        result[src] = any(c.replace("\\", "/") in test_files for c in candidates)

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def verify_findings(findings: list[Finding], files: list[ChangedFile]) -> list[Finding]:
    """Filter and calibrate review findings against the actual diff content.

    Multi-layer pipeline:
    0. Remove findings whose file is not in the changed-files set.
    1. Reject findings whose reported line is not an added/modified line.
    2. Downgrade style-only findings (→ P3 + [建议]) — runs before evidence
       check because formatting evidence naturally won't match code tokens.
    3. Reject non-style findings whose evidence cannot be cross-referenced
       with the diff content.
    4. Apply context-based severity downgrades (ignored files, removed files, etc.).
    5. Test-coverage confidence adjustment.
    6. Minimum-confidence filter (after adjustments).
    7. Minimum content-length filter.
    8. Exact dedup by (file, line, title).
    9. Semantic dedup by title similarity within (file, category).

    Graceful degradation: when ``patch`` is ``None`` the diff-based checks
    (steps 1 and 2) automatically accept the finding.
    """
    if not findings:
        return []

    # --- Pre-compute lookups ------------------------------------------------
    file_lookup: dict[str, ChangedFile] = {
        f.filename.replace("\\", "/"): f for f in files
    }
    added_line_map = _build_added_line_map(files)
    added_content_map: dict[str, list[dict]] = {
        f.filename.replace("\\", "/"): extract_added_lines(f.patch) for f in files
    }
    has_any_test_change = any(is_test_file(f.filename) for f in files)
    source_test_map = _build_source_test_map(files)

    # --- Per-finding filtering -----------------------------------------------
    verified: list[Finding] = []
    seen_exact: set[tuple[str, int, str]] = set()
    changed_files = {f.filename.replace("\\", "/") for f in files}

    for finding in findings:
        fname = finding.file.replace("\\", "/")

        # 0. File must be in the changed set
        if fname not in changed_files:
            continue

        # 1. Line must fall within an added/modified hunk
        valid_lines = added_line_map.get(fname, set())
        if finding.line <= 0:
            continue
        if valid_lines and finding.line not in valid_lines:
            continue

        # 2. Style-only → downgrade instead of delete (before evidence check because
        #    formatting-related evidence naturally won't match code tokens)
        is_style = _is_style_only(finding)
        if is_style:
            finding.severity = "P3"
            finding.tag = "[建议]"
            finding.confidence = max(finding.confidence, 0.55)

        # 3. Evidence must reference content actually present near that line.
        #    Style findings are exempt because their evidence describes formatting,
        #    not specific code tokens.
        if not is_style:
            added_content = added_content_map.get(fname, [])
            if not _evidence_matches_diff(finding, added_content):
                continue

        # 4. Context-based severity downgrade
        file_obj = file_lookup.get(fname)
        _apply_severity_downgrade(finding, file_obj)

        # 4a. Test-coverage confidence adjustment
        if file_obj and not is_test_file(file_obj.filename):
            if source_test_map.get(fname, False):
                # Corresponding test was changed — weak positive signal
                finding.confidence = max(0.0, min(1.0, finding.confidence * 0.95))
            elif not has_any_test_change and file_obj.risk_score >= 65:
                # No test files changed at all + high-risk file — elevate concern
                finding.confidence = max(0.0, min(1.0, finding.confidence * 1.08))

        # 5. Minimum confidence
        if finding.confidence < 0.55:
            continue

        # 6. Minimum content length
        if len(finding.evidence.strip()) < 8 or len(finding.suggestion.strip()) < 8:
            continue

        # 7. Exact dedup
        key = (fname, finding.line, finding.title.lower().strip())
        if key in seen_exact:
            continue
        seen_exact.add(key)
        verified.append(finding)

    # --- Post-processing -----------------------------------------------------
    # 8. Semantic dedup
    verified = _deduplicate_similar(verified)

    return verified
