import asyncio
import re
from pathlib import PurePosixPath

from app.analyzer.diff_parser import extract_added_lines, language_from_filename
from app.config import get_settings
from app.github.client import GitHubClient
from app.models.schemas import (
    ChangedFile,
    ChangedFileContext,
    ContextSnippet,
    ContextSummary,
    PrInfo,
    ReviewContext,
)


MODE_TARGETS = {"fast": 3, "standard": 5, "deep": 15}
CONFIG_PATTERNS = (
    ".ai-review.yml",
    ".github/",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "tsconfig.json",
    "vite.config",
    "dockerfile",
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".rb", ".php"}
TEXT_SUFFIXES = SOURCE_SUFFIXES | {".md", ".txt", ".yml", ".yaml", ".json", ".toml"}


class ContextCollector:
    def __init__(self, client: GitHubClient | None = None) -> None:
        self.client = client or GitHubClient()
        self.settings = get_settings()

    async def collect(self, pr: PrInfo, files: list[ChangedFile], mode: str) -> ReviewContext:
        limit = min(MODE_TARGETS.get(mode, 5), self.settings.max_context_files)
        targets = files[:limit]
        context = ReviewContext(
            summary=ContextSummary(
                available=False,
                mode=mode,
                target_files=[file.filename for file in targets],
            )
        )
        if not targets:
            context.notes.append("No changed files were available for context collection.")
            context.summary.notes = context.notes
            return context

        tree = await self.client.fetch_tree(pr.owner, pr.repo, pr.head_sha or pr.default_branch)
        tree_files = list(tree.get("files") or [])
        if tree.get("truncated"):
            context.notes.append("GitHub tree response was truncated.")
        if tree.get("note"):
            context.notes.append(f"Tree unavailable: {tree['note']}")

        related_tests = self._find_related_tests(targets, tree_files)
        repository_doc_paths = self._select_repository_docs(tree_files)
        context.summary.related_tests_checked = related_tests
        context.summary.repository_docs_checked = repository_doc_paths

        await asyncio.gather(
            *(self._attach_file_context(pr, file, tree_files, related_tests) for file in targets)
        )
        context.repository_docs = await self._fetch_repository_docs(pr, repository_doc_paths, mode)

        if mode != "fast":
            context.history = await self.client.search_issues(
                pr.owner,
                pr.repo,
                self._history_terms(pr, targets),
                limit=self.settings.max_history_items,
            )

        context.summary.changed_files_with_context = sum(1 for file in targets if file.context)
        context.summary.history_items = context.history
        context.summary.available = bool(
            context.summary.changed_files_with_context
            or context.repository_docs
            or context.summary.related_tests_checked
            or context.history
        )
        context.summary.notes = context.notes
        return context

    async def _attach_file_context(
        self,
        pr: PrInfo,
        file: ChangedFile,
        tree_files: list[str],
        all_related_tests: list[str],
    ) -> None:
        snippets: list[ContextSnippet] = []
        notes: list[str] = []
        base_ref = pr.base_sha
        head_ref = pr.head_sha or pr.default_branch
        head = await self.client.fetch_file_text(
            pr.owner, pr.repo, file.filename, head_ref, self.settings.max_context_file_chars
        )
        base = await self.client.fetch_file_text(
            pr.owner, pr.repo, file.filename, base_ref, self.settings.max_context_file_chars
        )

        head_text = head.get("content")
        base_text = base.get("content")
        if head.get("note"):
            notes.append(f"head: {head['note']}")
        if base.get("note") and file.status != "added":
            notes.append(f"base: {base['note']}")

        for snippet in self._changed_line_snippets(file, head_text, head_ref):
            snippets.append(snippet)
        for snippet in self._symbol_snippets(file, head_text, head_ref):
            snippets.append(snippet)
        if not snippets and base_text:
            snippets.append(self._file_head_snippet(file.filename, base_text, base_ref, "base_file_head"))

        file_tests = self._paths_related_to_file(file.filename, all_related_tests)
        related_files = self._find_neighbor_files(file.filename, tree_files)
        file.context = ChangedFileContext(
            base_ref=base_ref,
            head_ref=head_ref,
            snippets=self._dedupe_snippets(snippets)[:4],
            related_tests=file_tests,
            related_files=related_files,
            notes=notes,
        )

    async def _fetch_repository_docs(
        self, pr: PrInfo, paths: list[str], mode: str
    ) -> list[ContextSnippet]:
        limit = 2 if mode == "fast" else 5
        snippets: list[ContextSnippet] = []
        for path in paths[:limit]:
            result = await self.client.fetch_file_text(
                pr.owner, pr.repo, path, pr.head_sha or pr.default_branch, max_chars=8000
            )
            content = result.get("content")
            if not content:
                continue
            snippets.append(self._file_head_snippet(path, content, pr.head_sha or pr.default_branch, "repository_doc"))
        return snippets

    def _changed_line_snippets(
        self, file: ChangedFile, text: str | None, ref: str | None
    ) -> list[ContextSnippet]:
        if not text:
            return []
        lines = text.splitlines()
        snippets: list[ContextSnippet] = []
        for added in extract_added_lines(file.patch)[:3]:
            line = int(added["line"])
            start = max(1, line - 8)
            end = min(len(lines), line + 8)
            snippets.append(
                ContextSnippet(
                    kind="changed_hunk_context",
                    path=file.filename,
                    ref=ref,
                    start_line=start,
                    end_line=end,
                    language=language_from_filename(file.filename),
                    content="\n".join(lines[start - 1 : end]),
                )
            )
        return snippets

    def _symbol_snippets(
        self, file: ChangedFile, text: str | None, ref: str | None
    ) -> list[ContextSnippet]:
        if not text or PurePosixPath(file.filename).suffix.lower() not in SOURCE_SUFFIXES:
            return []
        added_lines = extract_added_lines(file.patch)
        if not added_lines:
            return []
        line = int(added_lines[0]["line"])
        lines = text.splitlines()
        start = self._nearest_symbol_start(lines, line)
        if start is None:
            return []
        end = self._symbol_end(lines, start)
        return [
            ContextSnippet(
                kind="symbol_context",
                path=file.filename,
                ref=ref,
                start_line=start,
                end_line=end,
                language=language_from_filename(file.filename),
                content="\n".join(lines[start - 1 : end]),
            )
        ]

    def _nearest_symbol_start(self, lines: list[str], line: int) -> int | None:
        symbol_pattern = re.compile(
            r"^\s*(async\s+)?(def|class|function)\s+|^\s*(export\s+)?(async\s+)?(function|class)\s+"
            r"|^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s*)?\("
        )
        for index in range(min(line - 1, len(lines) - 1), -1, -1):
            if symbol_pattern.search(lines[index]):
                return index + 1
        return None

    def _symbol_end(self, lines: list[str], start: int) -> int:
        base_indent = len(lines[start - 1]) - len(lines[start - 1].lstrip())
        end = min(len(lines), start + 80)
        for index in range(start, min(len(lines), start + 80)):
            stripped = lines[index].strip()
            indent = len(lines[index]) - len(lines[index].lstrip())
            if stripped and indent <= base_indent and re.match(r"(def|class|function|export|const|let|var)\b", stripped):
                return index
        return end

    def _file_head_snippet(self, path: str, text: str, ref: str | None, kind: str) -> ContextSnippet:
        lines = text.splitlines()
        end = min(len(lines), 80)
        return ContextSnippet(
            kind=kind,
            path=path,
            ref=ref,
            start_line=1,
            end_line=end,
            language=language_from_filename(path),
            content="\n".join(lines[:end]),
        )

    def _find_related_tests(self, targets: list[ChangedFile], tree_files: list[str]) -> list[str]:
        changed = {file.filename for file in targets}
        test_files = [path for path in tree_files if self._is_test_path(path)]
        selected: list[str] = []
        for target in targets:
            selected.extend(self._paths_related_to_file(target.filename, test_files))
        selected.extend(path for path in changed if self._is_test_path(path))
        return self._dedupe_paths(selected)[: self.settings.max_related_files]

    def _find_neighbor_files(self, filename: str, tree_files: list[str]) -> list[str]:
        path = PurePosixPath(filename)
        stem = path.stem.replace(".test", "").replace(".spec", "")
        parent = str(path.parent)
        candidates = []
        for item in tree_files:
            other = PurePosixPath(item)
            if item == filename or other.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if str(other.parent) == parent or other.stem.startswith(stem) or stem in other.stem:
                candidates.append(item)
        return self._dedupe_paths(candidates)[:4]

    def _paths_related_to_file(self, filename: str, paths: list[str]) -> list[str]:
        target = PurePosixPath(filename)
        target_parts = set(target.parts)
        stem = target.stem
        if stem.endswith((".test", ".spec")):
            stem = stem.rsplit(".", 1)[0]
        related: list[str] = []
        for path in paths:
            candidate = PurePosixPath(path)
            if candidate.stem.startswith(stem) or stem in candidate.stem:
                related.append(path)
                continue
            if str(candidate.parent) == str(target.parent):
                related.append(path)
                continue
            if "tests" in candidate.parts and target_parts.intersection(candidate.parts):
                related.append(path)
        return self._dedupe_paths(related)[: self.settings.max_related_files]

    def _select_repository_docs(self, tree_files: list[str]) -> list[str]:
        docs: list[str] = []
        for path in tree_files:
            lower = path.lower()
            name = PurePosixPath(path).name.lower()
            if name.startswith("readme") or lower.startswith("docs/"):
                docs.append(path)
            elif lower.startswith(CONFIG_PATTERNS) or any(lower.endswith(pattern) for pattern in CONFIG_PATTERNS):
                docs.append(path)
        return self._dedupe_paths(docs)[: self.settings.max_related_files]

    def _history_terms(self, pr: PrInfo, targets: list[ChangedFile]) -> list[str]:
        terms = re.findall(r"[A-Za-z0-9_-]{3,}", pr.title or "")
        for file in targets[:5]:
            path = PurePosixPath(file.filename)
            terms.extend([path.stem, *(part for part in path.parts[:-1] if len(part) >= 3)])
        return self._dedupe_paths(terms)[:8]

    def _is_test_path(self, path: str) -> bool:
        lower = path.lower()
        return (
            "/test/" in f"/{lower}"
            or "/tests/" in f"/{lower}"
            or lower.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".test.js", ".spec.js"))
        )

    def _dedupe_paths(self, paths: list[str]) -> list[str]:
        result: list[str] = []
        for path in paths:
            if path and path not in result:
                result.append(path)
        return result

    def _dedupe_snippets(self, snippets: list[ContextSnippet]) -> list[ContextSnippet]:
        result: list[ContextSnippet] = []
        seen: set[tuple[str, str, int | None, int | None]] = set()
        for snippet in snippets:
            key = (snippet.kind, snippet.path, snippet.start_line, snippet.end_line)
            if key not in seen and snippet.content:
                seen.add(key)
                result.append(snippet)
        return result
