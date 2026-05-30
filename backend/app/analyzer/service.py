from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.analyzer.report_generator import build_github_comment
from app.analyzer.reviewer import review_pr
from app.analyzer.risk_classifier import classify_files
from app.analyzer.verifier import verify_findings
from app.db.models import ChangedFileRecord, FindingRecord, ReportRecord
from app.db.session import SessionLocal
from app.github.client import GitHubClient
from app.github.parser import parse_pr_url
from app.models.schemas import ChangedFile, PrInfo, ReportResult, ReportSummaryItem


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class AnalysisCancelled(Exception):
    pass


def create_report(
    db: Session,
    pr_url: str,
    mode: str = "standard",
    retry_of: str | None = None,
    attempt_count: int = 1,
) -> ReportRecord:
    report = ReportRecord(
        pr_url=pr_url,
        mode=mode,
        retry_of=retry_of,
        attempt_count=attempt_count,
        status="queued",
        progress=0,
        current_step="Queued",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


async def analyze_report(report_id: str, pr_url: str, mode: str) -> None:
    db = SessionLocal()
    started_at = datetime.utcnow()
    try:
        report = db.get(ReportRecord, report_id)
        if not report:
            return
        _mark(db, report, "running", 10, "正在解析 PR 地址")
        _raise_if_cancelled(db, report)

        ref = parse_pr_url(pr_url)
        _mark(db, report, "running", 20, "正在拉取 GitHub PR")
        _raise_if_cancelled(db, report)
        pr_payload = await GitHubClient().fetch_pull_request(ref)
        _raise_if_cancelled(db, report)

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
        _raise_if_cancelled(db, report)
        file_risks = classify_files(raw_files)

        _mark(db, report, "running", 70, "正在生成评审建议")
        _raise_if_cancelled(db, report)
        review = await review_pr(
            pr,
            file_risks,
            mode,
            status_callback=lambda progress, step: _mark(db, report, "running", progress, step),
        )
        _raise_if_cancelled(db, report)
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
        report.analysis_detail = review.source_detail
        report.github_comment_markdown = markdown
        report.status = "completed"
        report.progress = 100
        report.current_step = "分析完成"
        report.completed_at = datetime.utcnow()
        report.duration_seconds = int((report.completed_at - started_at).total_seconds())
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
    except AnalysisCancelled:
        pass
    except Exception as exc:
        report = db.get(ReportRecord, report_id)
        if report:
            report.status = "failed"
            report.progress = 100
            report.current_step = "分析失败"
            report.error = str(exc)
            report.completed_at = datetime.utcnow()
            report.duration_seconds = int((report.completed_at - started_at).total_seconds())
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
        analysis_detail=report.analysis_detail,
    )


def list_report_summaries(db: Session, limit: int = 20) -> list[ReportSummaryItem]:
    reports = (
        db.query(ReportRecord)
        .options(joinedload(ReportRecord.files), joinedload(ReportRecord.findings))
        .order_by(ReportRecord.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        ReportSummaryItem(
            report_id=report.id,
            pr_url=report.pr_url,
            mode=report.mode or "standard",
            status=report.status,
            progress=report.progress,
            current_step=report.current_step,
            title=report.title,
            owner=report.owner,
            repo=report.repo,
            pull_number=report.pull_number,
            finding_count=len(report.findings),
            high_risk_file_count=sum(
                1 for item in report.files if item.risk_level in {"critical", "high"}
            ),
            created_at=report.created_at.isoformat(),
            updated_at=report.updated_at.isoformat(),
            completed_at=report.completed_at.isoformat() if report.completed_at else None,
            duration_seconds=report.duration_seconds,
            retry_of=report.retry_of,
            error=report.error,
        )
        for report in reports
    ]


def _mark(db: Session, report: ReportRecord, status: str, progress: int, step: str) -> None:
    report.status = status
    report.progress = progress
    report.current_step = step
    db.commit()


def _raise_if_cancelled(db: Session, report: ReportRecord) -> None:
    db.refresh(report)
    if not report.cancel_requested:
        return
    report.status = "cancelled"
    report.current_step = "已取消"
    report.completed_at = datetime.utcnow()
    db.commit()
    raise AnalysisCancelled()
