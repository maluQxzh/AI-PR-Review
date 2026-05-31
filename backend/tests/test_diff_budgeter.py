from app.analyzer.diff_budgeter import build_budgeted_review_files, compact_patch_for_review
from app.models.schemas import ChangedFile


def test_budgeter_keeps_small_high_risk_patch_full():
    files = [
        ChangedFile(
            filename="backend/app/auth.py",
            status="modified",
            additions=2,
            deletions=0,
            patch="@@ -1 +1,2 @@\n+if user.role == 'admin':\n+    return True\n",
            risk_score=95,
            risk_level="critical",
            risk_dimensions=["security"],
        )
    ]

    budgeted, summary = build_budgeted_review_files(files, "standard")

    assert budgeted[0].review_input_kind == "full_patch"
    assert "return True" in budgeted[0].patch
    assert summary["kind_counts"]["full_patch"] == 1


def test_budgeter_compacts_large_patch_and_keeps_risky_lines():
    noisy_lines = "\n".join(f"+value_{i} = {i}" for i in range(1200))
    patch = (
        "@@ -1 +1,505 @@\n"
        "+def check_permission(user):\n"
        "+    if user.role == 'admin':\n"
        "+        return True\n"
        f"{noisy_lines}\n"
    )
    files = [
        ChangedFile(
            filename="src/auth/check.py",
            status="modified",
            additions=1205,
            patch=patch,
            risk_score=90,
            risk_level="critical",
            risk_dimensions=["security"],
        )
    ]

    budgeted, _ = build_budgeted_review_files(files, "fast", max_files=1)

    assert budgeted[0].review_input_kind == "compact_patch"
    assert len(budgeted[0].patch) < len(patch)
    assert "check_permission" in budgeted[0].patch
    assert "return True" in budgeted[0].patch


def test_budgeter_summarizes_non_sensitive_delete_only_hunk():
    patch = "@@ -10,3 +10,0 @@\n-old helper\n-unused value\n-old comment\n"
    files = [
        ChangedFile(
            filename="src/cleanup.py",
            status="modified",
            deletions=3,
            patch=patch,
            risk_score=20,
            risk_level="low",
        )
    ]

    budgeted, _ = build_budgeted_review_files(files, "standard")

    assert budgeted[0].review_input_kind == "summary_only"
    assert budgeted[0].patch == ""
    assert "delete-only" in budgeted[0].compression_note


def test_compact_patch_handles_multiple_hunks_with_budget():
    patch = (
        "@@ -1,3 +1,5 @@\n"
        "+def low_value():\n"
        "+    x = 1\n"
        "+    y = 2\n"
        "@@ -50,3 +52,5 @@\n"
        "+def authorize(user):\n"
        "+    if not user.role:\n"
        "+        return False\n"
    )

    compact = compact_patch_for_review(patch, 120)

    assert "@@ -50" in compact
    assert "authorize" in compact
    assert len(compact) <= 160
