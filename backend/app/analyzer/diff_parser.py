from fnmatch import fnmatch
from pathlib import Path


IGNORE_PATTERNS = [
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "dist/**",
    "build/**",
    "*.min.js",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.ico",
]


def should_review_file(filename: str, total_files: int = 1) -> bool:
    normalized = filename.replace("\\", "/")
    if total_files <= 1 and normalized.endswith(("lock", ".lock")):
        return True
    return not any(fnmatch(normalized, pattern) for pattern in IGNORE_PATTERNS)


def language_from_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript/react",
        ".js": "javascript",
        ".jsx": "javascript/react",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".rs": "rust",
        ".php": "php",
        ".sql": "sql",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".json": "json",
    }.get(suffix, suffix.lstrip(".") or "text")


def extract_added_lines(patch: str | None) -> list[dict[str, int | str]]:
    if not patch:
        return []

    added: list[dict[str, int | str]] = []
    new_line = 0
    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            marker = raw_line.split("+", 1)[1].split(" ", 1)[0]
            start = marker.split(",", 1)[0]
            new_line = int(start) - 1
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            new_line += 1
            added.append({"line": new_line, "content": raw_line[1:]})
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        else:
            new_line += 1
    return added


def compact_patch(patch: str | None, max_chars: int) -> str:
    if not patch:
        return ""
    if len(patch) <= max_chars:
        return patch
    head = patch[: max_chars // 2]
    tail = patch[-max_chars // 2 :]
    return f"{head}\n\n... patch truncated for demo speed ...\n\n{tail}"
