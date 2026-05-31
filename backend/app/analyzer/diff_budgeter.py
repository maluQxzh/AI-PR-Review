from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from app.analyzer.diff_parser import language_from_filename, should_review_file
from app.models.schemas import ChangedFile


MODE_POLICIES = {
    "fast": {"budget_chars": 30_000, "rich_files": 3, "max_files": 20},
    "standard": {"budget_chars": 90_000, "rich_files": 8, "max_files": 40},
    "deep": {"budget_chars": 180_000, "rich_files": 20, "max_files": 100},
}

HIGH_VALUE_PATH_RE = re.compile(
    r"auth|permission|security|crypto|payment|database|migration|schema|api|route|config|settings",
    re.I,
)
HIGH_VALUE_LINE_RE = re.compile(
    r"auth|permission|token|jwt|session|password|secret|admin|role|allow|deny|"
    r"validate|check|assert|schema|migration|select|insert|update|delete|"
    r"fetch|httpx|requests|axios|except|catch|throw|raise|return|if |else|await|async",
    re.I,
)
FUNCTION_LINE_RE = re.compile(
    r"^\s*(async\s+)?(def|class|function)\s+|^\s*(export\s+)?(async\s+)?(function|class)\s+|"
    r"^\s*(export\s+)?(const|let|var)\s+\w+\s*=",
    re.I,
)
GENERATED_PATH_RE = re.compile(r"(^|/)(dist|build|coverage|vendor|node_modules)/|generated|\.min\.", re.I)
LOCK_OR_BINARY_RE = re.compile(
    r"(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|poetry\.lock|Cargo\.lock)$|"
    r"\.(png|jpe?g|gif|webp|svg|woff2?|ttf|ico|pdf|zip)$",
    re.I,
)
DOC_SUFFIXES = {".md", ".txt", ".rst", ".adoc"}


@dataclass(frozen=True)
class BudgetedReviewFile:
    filename: str
    status: str
    additions: int
    deletions: int
    language: str
    risk_score: int
    risk_level: str
    risk_dimensions: list[str]
    risk_reasons: list[str]
    review_input_kind: str
    patch: str
    compression_note: str
    context: dict[str, Any] | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "language": self.language,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "risk_dimensions": self.risk_dimensions,
            "risk_reasons": self.risk_reasons,
            "review_input_kind": self.review_input_kind,
            "compression_note": self.compression_note,
            "patch": self.patch,
            "context": self.context,
        }


def build_budgeted_review_files(
    files: list[ChangedFile],
    mode: str,
    max_files: int | None = None,
) -> tuple[list[BudgetedReviewFile], dict[str, Any]]:
    policy = MODE_POLICIES.get(mode, MODE_POLICIES["standard"])
    total_budget = int(policy["budget_chars"])
    rich_limit = int(policy["rich_files"])
    policy_file_limit = int(policy["max_files"])
    file_limit = min(policy_file_limit, max_files or policy_file_limit)

    ranked = sorted(files, key=review_priority, reverse=True)
    selected = ranked[:file_limit]
    remaining = total_budget
    budgeted: list[BudgetedReviewFile] = []

    for index, file in enumerate(selected):
        full_patch = file.patch or ""
        summary_reason = summary_only_reason(file)
        context = file.context.model_dump() if file.context else None

        if summary_reason:
            budgeted.append(_budgeted(file, "summary_only", "", summary_reason, context))
            continue

        if not full_patch:
            budgeted.append(_budgeted(file, "summary_only", "", "no patch available from GitHub", context))
            continue

        full_cap = max(8_000, total_budget // 4)
        if index < rich_limit and len(full_patch) <= remaining and len(full_patch) <= full_cap:
            budgeted.append(_budgeted(file, "full_patch", full_patch, "full patch included", context))
            remaining -= len(full_patch)
            continue

        target = min(max(2_500, remaining // max(1, file_limit - len(budgeted))), 12_000)
        compact = compact_patch_for_review(full_patch, target)
        if compact and len(compact) <= remaining:
            budgeted.append(
                _budgeted(file, "compact_patch", compact, f"patch compacted to {len(compact)} chars", context)
            )
            remaining -= len(compact)
        elif compact and remaining >= 1_200:
            compact = compact_patch_for_review(full_patch, remaining)
            budgeted.append(
                _budgeted(file, "compact_patch", compact, f"patch compacted to remaining {remaining} chars", context)
            )
            remaining = 0
        else:
            budgeted.append(
                _budgeted(file, "summary_only", "", "patch omitted because review budget was exhausted", context)
            )

    kind_counts = {
        "full_patch": sum(1 for item in budgeted if item.review_input_kind == "full_patch"),
        "compact_patch": sum(1 for item in budgeted if item.review_input_kind == "compact_patch"),
        "summary_only": sum(1 for item in budgeted if item.review_input_kind == "summary_only"),
        "skipped": max(0, len(files) - len(selected)),
    }
    summary = {
        "mode": mode,
        "total_changed_files": len(files),
        "review_input_files": len(budgeted),
        "budget_chars": total_budget,
        "used_patch_chars": total_budget - remaining,
        "remaining_patch_chars": max(0, remaining),
        "kind_counts": kind_counts,
    }
    return budgeted, summary


def select_review_candidates(files: list[ChangedFile], mode: str, max_files: int | None = None) -> list[ChangedFile]:
    policy = MODE_POLICIES.get(mode, MODE_POLICIES["standard"])
    limit = min(int(policy["max_files"]), max_files or int(policy["max_files"]))
    return sorted(files, key=review_priority, reverse=True)[:limit]


def review_priority(file: ChangedFile) -> int:
    normalized = file.filename.replace("\\", "/").lower()
    suffix = PurePosixPath(normalized).suffix
    score = int(file.risk_score)

    if HIGH_VALUE_PATH_RE.search(normalized):
        score += 18
    if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".rb", ".php", ".sql"}:
        score += 8
    if suffix in {".json", ".yml", ".yaml", ".toml"}:
        score += 5
    if _is_test_path(normalized):
        score += 4
        if any(dim in {"security", "data", "compatibility", "test_gap"} for dim in file.risk_dimensions):
            score += 6
    if not should_review_file(file.filename, total_files=2) or GENERATED_PATH_RE.search(normalized):
        score -= 45
    if LOCK_OR_BINARY_RE.search(normalized):
        score -= 60
    if suffix in DOC_SUFFIXES and file.risk_score < 65:
        score -= 20
    if file.status == "removed":
        score -= 6

    return score


def compact_patch_for_review(patch: str | None, max_chars: int) -> str:
    if not patch or max_chars <= 0:
        return ""
    if len(patch) <= max_chars:
        return patch

    hunks = _split_hunks(patch)
    if not hunks:
        return patch[:max_chars]

    rendered: list[str] = []
    for hunk in sorted(hunks, key=_hunk_priority, reverse=True):
        text = _render_hunk(hunk)
        if not text:
            continue
        if _append_with_budget(rendered, text, max_chars):
            continue
        if not rendered:
            rendered.append(text[: max(0, max_chars - 40)] + "\n... hunk truncated ...")
        break

    compact = "\n".join(rendered).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 80)] + "\n... compact patch truncated ..."


def summary_only_reason(file: ChangedFile) -> str | None:
    normalized = file.filename.replace("\\", "/").lower()
    suffix = PurePosixPath(normalized).suffix
    if not should_review_file(file.filename, total_files=2):
        return "low-value generated, binary, lock, or build artifact"
    if GENERATED_PATH_RE.search(normalized) or LOCK_OR_BINARY_RE.search(normalized):
        return "generated, binary, lock, or build artifact"
    if suffix in DOC_SUFFIXES and file.risk_score < 65 and (file.additions + file.deletions) > 80:
        return "large documentation-only change summarized"
    if _is_delete_only(file.patch) and not _delete_only_has_sensitive_lines(file.patch or "", file.filename):
        return "delete-only hunk summarized without deleted body"
    return None


def _budgeted(
    file: ChangedFile,
    kind: str,
    patch: str,
    note: str,
    context: dict[str, Any] | None,
) -> BudgetedReviewFile:
    return BudgetedReviewFile(
        filename=file.filename,
        status=file.status,
        additions=file.additions,
        deletions=file.deletions,
        language=language_from_filename(file.filename),
        risk_score=file.risk_score,
        risk_level=file.risk_level,
        risk_dimensions=file.risk_dimensions,
        risk_reasons=file.risk_reasons,
        review_input_kind=kind,
        patch=patch,
        compression_note=note,
        context=context,
    )


def _split_hunks(patch: str) -> list[list[str]]:
    hunks: list[list[str]] = []
    current: list[str] = []
    for line in patch.splitlines():
        if line.startswith("@@"):
            if current:
                hunks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        hunks.append(current)
    return hunks


def _render_hunk(hunk: list[str]) -> str:
    header = hunk[0]
    added = [line for line in hunk[1:] if line.startswith("+") and not line.startswith("+++")]
    deleted = [line for line in hunk[1:] if line.startswith("-") and not line.startswith("---")]
    context = [line for line in hunk[1:] if not line.startswith(("+", "-"))]

    lines: list[str] = [header]
    if deleted and not added:
        lines.append(f"... delete-only hunk: {len(deleted)} removed lines ...")
        lines.extend(_important_lines(deleted, limit=8))
        return "\n".join(lines)

    lines.extend(_important_lines(context, limit=4))
    lines.extend(_important_lines(added, limit=36))
    if len(added) > 36:
        lines.append(f"... {len(added) - 36} additional added lines omitted ...")
    if deleted:
        important_deleted = _important_lines(deleted, limit=8)
        if important_deleted:
            lines.append(f"... {len(deleted)} removed lines, important removals follow ...")
            lines.extend(important_deleted)
    return "\n".join(lines)


def _important_lines(lines: list[str], limit: int) -> list[str]:
    important = [
        line
        for line in lines
        if HIGH_VALUE_LINE_RE.search(line) or FUNCTION_LINE_RE.search(line) or line.startswith("@@")
    ]
    if len(important) < min(limit, len(lines)):
        for line in lines:
            if line.strip() and line not in important:
                important.append(line)
            if len(important) >= limit:
                break
    return important[:limit]


def _hunk_priority(hunk: list[str]) -> int:
    text = "\n".join(hunk)
    score = 0
    score += len(HIGH_VALUE_LINE_RE.findall(text)) * 5
    score += len(FUNCTION_LINE_RE.findall(text)) * 4
    score += sum(1 for line in hunk if line.startswith("+") and not line.startswith("+++"))
    if _is_delete_only("\n".join(hunk)):
        score -= 8
    return score


def _append_with_budget(rendered: list[str], text: str, max_chars: int) -> bool:
    current_len = sum(len(item) + 1 for item in rendered)
    if current_len + len(text) + 1 > max_chars:
        return False
    rendered.append(text)
    return True


def _is_delete_only(patch: str | None) -> bool:
    if not patch:
        return False
    has_added = any(line.startswith("+") and not line.startswith("+++") for line in patch.splitlines())
    has_deleted = any(line.startswith("-") and not line.startswith("---") for line in patch.splitlines())
    return has_deleted and not has_added


def _delete_only_has_sensitive_lines(patch: str, filename: str) -> bool:
    if HIGH_VALUE_PATH_RE.search(filename):
        return True
    deleted_text = "\n".join(
        line[1:] for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")
    )
    return bool(HIGH_VALUE_LINE_RE.search(deleted_text))


def _is_test_path(path: str) -> bool:
    return "test" in path or "spec" in path or path.endswith(("_test.py", ".test.ts", ".spec.ts"))
