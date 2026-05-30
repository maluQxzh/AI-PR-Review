from sqlalchemy.orm import Session, joinedload

from app.analyzer.report_generator import build_github_comment
from app.analyzer.reviewer import review_pr
from app.analyzer.risk_classifier import classify_files
from app.analyzer.verifier import verify_findings
from app.db.models import ChangedFileRecord, FindingRecord, ReportRecord
from app.db.session import SessionLocal
from app.github.client import GitHubClient
from app.github.parser import parse_pr_url
from app.models.schemas import ChangedFile, PrInfo, ReportResult


def create_report(db: Session, pr_url: str) -> ReportRecord:
    report = ReportRecord(pr_url=pr_url, status="queued", progress=0, current_step="Queued")
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


async def analyze_report(report_id: str, pr_url: str, mode: str) -> None:
    db = SessionLocal()
    try:
        report = db.get(ReportRecord, report_id)
        if not report:
            return
        _mark(db, report, "running", 10, "正在解析 PR 地址")

        ref = parse_pr_url(pr_url)
        _mark(db, report, "running", 20, "正在拉取 GitHub PR")
        pr_payload = await GitHubClient().fetch_pull_request(ref)

        pr = PrInfo(**{key: value for key, value in pr_payload.items() if key != "files"})
        raw_files = [
            ChangedFile(
                filename=item["filename"],
                status=item["status"],
                additions=item.get("additions", 0),
                deletions=item.get("deletions", 0),
                patch=item.get("patch"),
            )
            for item in pr_payload.get("files", [])
        ]

        _mark(db, report, "running", 45, "正在识别文件风险")
        file_risks = classify_files(raw_files)

        _mark(db, report, "running", 70, "正在生成评审建议")
        review = await review_pr(pr, file_risks, mode)
        findings = verify_findings(review.findings, file_risks)
        markdown = build_github_comment(
            pr, review.summary, file_risks, findings, review.test_suggestions
        )

        report.owner = pr.owner
        report.repo = pr.repo
        report.pull_number = pr.number
        report.title = pr.title
        report.pr_data = pr.model_dump()
        report.summary = review.summary.model_dump()
        report.test_suggestions = [item.model_dump() for item in review.test_suggestions]
        report.analysis_source = review.source
        report.github_comment_markdown = markdown
        report.status = "completed"
        report.progress = 100
        report.current_step = "分析完成"
        report.files = [
            ChangedFileRecord(
                filename=item.filename,
                status=item.status,
                additions=item.additions,
                deletions=item.deletions,
                patch=item.patch,
                risk_level=item.risk_level,
                risk_score=item.risk_score,
                risk_reasons=item.risk_reasons,
            )
            for item in file_risks
        ]
        report.findings = [FindingRecord(**item.model_dump()) for item in findings]
        db.commit()
    except Exception as exc:
        report = db.get(ReportRecord, report_id)
        if report:
            report.status = "failed"
            report.progress = 100
            report.current_step = "分析失败"
            report.error = str(exc)
            db.commit()
    finally:
        db.close()


def get_report_result(db: Session, report_id: str) -> ReportResult | None:
    report = (
        db.query(ReportRecord)
        .options(joinedload(ReportRecord.files), joinedload(ReportRecord.findings))
        .filter(ReportRecord.id == report_id)
        .first()
    )
    if not report:
        return None

    pr = PrInfo.model_validate(report.pr_data) if report.pr_data else None
    return ReportResult(
        report_id=report.id,
        status=report.status,
        analysis_source=report.analysis_source or "unknown",
        pr=pr,
        summary=report.summary,
        file_risks=[
            ChangedFile(
                filename=item.filename,
                status=item.status,
                additions=item.additions,
                deletions=item.deletions,
                patch=item.patch,
                risk_level=item.risk_level,
                risk_score=item.risk_score,
                risk_reasons=item.risk_reasons,
            )
            for item in sorted(report.files, key=lambda file: file.risk_score, reverse=True)
        ],
        findings=[
            {
                "title": item.title,
                "severity": item.severity,
                "confidence": item.confidence,
                "category": item.category,
                "file": item.file,
                "line": item.line,
                "evidence": item.evidence,
                "impact": item.impact,
                "suggestion": item.suggestion,
                "comment_draft": item.comment_draft,
            }
            for item in report.findings
        ],
        test_suggestions=report.test_suggestions or [],
        github_comment_markdown=report.github_comment_markdown or "",
        error=report.error,
    )


def _mark(db: Session, report: ReportRecord, status: str, progress: int, step: str) -> None:
    report.status = status
    report.progress = progress
    report.current_step = step
    db.commit()
