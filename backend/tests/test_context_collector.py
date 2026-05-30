import asyncio

from app.analyzer.context_collector import ContextCollector
from app.models.schemas import ChangedFile, PrInfo


class FakeClient:
    async def fetch_tree(self, owner, repo, ref):
        return {
            "files": [
                "README.md",
                "docs/security.md",
                ".github/workflows/ci.yml",
                "src/payment/authorize.ts",
                "src/payment/authorize.test.ts",
                "src/payment/helpers.ts",
            ],
            "truncated": False,
            "note": None,
        }

    async def fetch_file_text(self, owner, repo, path, ref, max_chars=None):
        content = {
            "src/payment/authorize.ts": (
                "export function authorize(user) {\n"
                "  if (!user.role) {\n"
                "    return true;\n"
                "  }\n"
                "  return hasPermission(user, 'payment:write');\n"
                "}\n"
            ),
            "README.md": "# Checkout service\n\nPayment service conventions.",
            "docs/security.md": "Authorization must deny by default.",
            ".github/workflows/ci.yml": "name: ci",
        }.get(path)
        return {"path": path, "ref": ref, "content": content, "note": None}

    async def search_issues(self, owner, repo, terms, limit=None):
        return [{"title": "Payment authorization policy", "state": "closed", "kind": "issue"}]


def test_context_collector_adds_changed_file_docs_tests_and_history():
    pr = PrInfo(
        owner="demo",
        repo="repo",
        number=1,
        title="Payment authorization",
        base_sha="base",
        head_sha="head",
        default_branch="main",
    )
    files = [
        ChangedFile(
            filename="src/payment/authorize.ts",
            status="modified",
            additions=3,
            patch="@@ -1,4 +1,6 @@\n export function authorize(user) {\n+  if (!user.role) {\n+    return true;\n+  }\n }\n",
        )
    ]

    context = asyncio.run(ContextCollector(FakeClient()).collect(pr, files, "standard"))

    assert context.summary.available is True
    assert context.summary.changed_files_with_context == 1
    assert "src/payment/authorize.test.ts" in context.summary.related_tests_checked
    assert "README.md" in context.summary.repository_docs_checked
    assert context.history[0]["title"] == "Payment authorization policy"
    assert files[0].context is not None
    assert files[0].context.snippets[0].kind == "changed_hunk_context"


def test_context_collector_keeps_running_when_tree_is_unavailable():
    class NoTreeClient(FakeClient):
        async def fetch_tree(self, owner, repo, ref):
            return {"files": [], "truncated": False, "note": "github returned 403"}

    pr = PrInfo(owner="demo", repo="repo", number=1, title="Demo", head_sha="head")
    files = [ChangedFile(filename="src/app.ts", status="modified", patch="@@ -1 +1 @@\n+run()\n")]

    context = asyncio.run(ContextCollector(NoTreeClient()).collect(pr, files, "fast"))

    assert "Tree unavailable: github returned 403" in context.notes
    assert context.summary.mode == "fast"
