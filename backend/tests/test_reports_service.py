from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analyzer.service import create_report, get_report_result, list_report_summaries
from app.db.models import ChangedFileRecord, FindingRecord
from app.db.session import Base


def test_report_summary_includes_retry_and_counts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine)
    db = session_local()
    try:
        report = create_report(
            db,
            "https://github.com/demo-org/checkout-service/pull/42",
            mode="deep",
            retry_of="original-report",
            attempt_count=2,
        )
        report.status = "completed"
        report.progress = 100
        report.title = "Demo PR"
        report.owner = "demo-org"
        report.repo = "checkout-service"
        report.pull_number = 42
        report.pr_data = {
            "owner": "demo-org",
            "repo": "checkout-service",
            "number": 42,
            "title": "Demo PR",
        }
        report.summary = {
            "what_changed": "Changed payment behavior.",
            "risk_overview": "High risk.",
            "review_focus": ["security"],
        }
        report.generated_artifacts = {
            "pr_metadata": {
                "suggested_title": "security: Demo PR",
                "pr_type": "security",
                "labels": [{"name": "type:security", "reason": "Security risk", "confidence": 0.8}],
            },
            "pr_description": {
                "summary": "Changed payment behavior.",
                "walkthrough": [],
                "testing": ["Run auth tests."],
                "risks": ["Authorization regression."],
                "rollback": "Revert the PR.",
                "markdown": "## Summary\nChanged payment behavior.",
            },
            "code_improvements": [],
            "documentation_suggestions": [],
            "changelog": {"category": "security", "entry": "Security: changed payment behavior."},
            "similar_items": [],
        }
        report.files = [
            ChangedFileRecord(
                filename="src/payment/authorize.ts",
                status="modified",
                risk_level="critical",
                risk_score=92,
            ),
            ChangedFileRecord(
                filename="README.md",
                status="modified",
                risk_level="low",
                risk_score=12,
            ),
        ]
        report.findings = [
            FindingRecord(
                file="src/payment/authorize.ts",
                line=22,
                title="Missing authorization guard",
                severity="P1",
                category="security",
                confidence=0.9,
                evidence="return true",
                impact="Unauthorized writes",
                suggestion="Deny by default",
                comment_draft="Please deny by default.",
            )
        ]
        db.commit()

        summaries = list_report_summaries(db)

        assert len(summaries) == 1
        assert summaries[0].mode == "deep"
        assert summaries[0].retry_of == "original-report"
        assert summaries[0].finding_count == 1
        assert summaries[0].high_risk_file_count == 1

        result = get_report_result(db, report.id)
        assert result is not None
        assert result.generated_artifacts is not None
        assert result.generated_artifacts.pr_metadata.pr_type == "security"
    finally:
        db.close()
