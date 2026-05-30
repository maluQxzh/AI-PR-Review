from app.analyzer.verifier import verify_findings
from app.models.schemas import ChangedFile, Finding


def test_verifier_removes_unbacked_findings():
    files = [ChangedFile(filename="src/app.ts", status="modified")]
    findings = [
        Finding(
            title="Real issue",
            severity="P2",
            confidence=0.8,
            category="logic",
            file="src/app.ts",
            line=4,
            evidence="Changed branch can return null.",
            impact="Callers may fail on null.",
            suggestion="Add a guard and test null behavior.",
            comment_draft="Please cover the null behavior.",
        ),
        Finding(
            title="Other file",
            severity="P2",
            confidence=0.8,
            category="logic",
            file="src/other.ts",
            line=4,
            evidence="Looks risky.",
            impact="Unknown.",
            suggestion="Please check.",
            comment_draft="Please check.",
        ),
    ]

    verified = verify_findings(findings, files)
    assert len(verified) == 1
    assert verified[0].title == "Real issue"
