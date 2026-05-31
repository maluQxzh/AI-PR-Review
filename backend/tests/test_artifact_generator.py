import inspect

from app.analyzer import artifact_generator
from app.analyzer.artifact_generator import build_fallback_artifacts, coerce_generated_artifacts
from app.analyzer.report_generator import build_comment_by_type
from app.models.schemas import ChangedFile, PrInfo, ReviewContext, Summary, TestSuggestion as SchemaTestSuggestion


def _pr() -> PrInfo:
    return PrInfo(
        owner="demo",
        repo="repo",
        number=12,
        title="Fix payment authorization",
        description="Payment bug fix",
        commits=[{"message": "fix auth fallback"}],
    )


def _files() -> list[ChangedFile]:
    return [
        ChangedFile(
            filename="src/payment/authorize.ts",
            status="modified",
            additions=10,
            deletions=2,
            patch="@@ -2,1 +2,2 @@\n+return true",
            risk_level="high",
            risk_score=81,
            risk_dimensions=["security", "test_gap"],
            risk_reasons=["Authorization behavior changed", "No tests changed"],
        )
    ]


def _summary() -> Summary:
    return Summary(
        what_changed="Payment authorization behavior changed.",
        risk_overview="High risk authorization change.",
        review_focus=["security", "tests"],
    )


def test_fallback_generates_pr_artifacts_and_similar_items():
    context = ReviewContext()
    context.history = [
        {
            "title": "Payment authorization should deny by default",
            "html_url": "https://github.com/demo/repo/issues/5",
            "state": "closed",
            "kind": "issue",
        }
    ]

    artifacts = build_fallback_artifacts(
        _pr(),
        _files(),
        _summary(),
        [],
        [SchemaTestSuggestion(title="Add auth tests", reason="Auth changed", suggested_case="Deny missing role.")],
        context,
    )

    assert artifacts.pr_metadata.pr_type == "security"
    assert any(label.name == "needs-tests" for label in artifacts.pr_metadata.labels)
    assert artifacts.pr_description.walkthrough[0].files == ["src/payment/authorize.ts"]
    assert artifacts.changelog is not None
    assert artifacts.similar_items[0].html_url.endswith("/issues/5")


def test_coerce_generated_artifacts_accepts_llm_json_and_fills_missing_fields():
    fallback = build_fallback_artifacts(_pr(), _files(), _summary(), [], [], None)
    artifacts = coerce_generated_artifacts(
        {
            "pr_metadata": {
                "suggested_title": "security: harden payment auth",
                "pr_type": "not-a-type",
                "labels": [{"name": "area:security", "reason": "Auth changed", "confidence": 1.3}],
            },
            "pr_description": {
                "summary": "Harden payment auth.",
                "walkthrough": [{"area": "payment", "files": ["a.ts"], "description": "Auth guard update."}],
            },
            "code_improvements": [{"file": "a.ts", "suggestion": "Name the default branch.", "title": "Clarify auth"}],
        },
        fallback,
    )

    assert artifacts.pr_metadata.suggested_title == "security: harden payment auth"
    assert artifacts.pr_metadata.pr_type == fallback.pr_metadata.pr_type
    assert artifacts.pr_metadata.labels[0].confidence == 1.0
    assert artifacts.pr_description.testing == fallback.pr_description.testing
    assert artifacts.code_improvements[0].file == "a.ts"


def test_artifacts_comment_type_returns_pr_preparation_markdown():
    artifacts = build_fallback_artifacts(_pr(), _files(), _summary(), [], [], None)
    markdown = build_comment_by_type("base", artifacts, "artifacts")

    assert "## PR Preparation" in markdown
    assert "Suggested title" in markdown
    assert artifacts.pr_metadata.suggested_title in markdown


def test_artifact_generator_has_no_hidden_llm_request():
    source = inspect.getsource(artifact_generator)

    assert "AsyncClient" not in source
    assert "chat/completions" not in source
