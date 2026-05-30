from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.analyzer.service import get_report_result
from app.db.models import ReportRecord
from app.db.session import get_db
from app.models.schemas import CommentRequest, CommentResponse, ReportResult, ReportStatus

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports/{report_id}", response_model=ReportStatus)
def get_report_status(report_id: str, db: Session = Depends(get_db)) -> ReportStatus:
    report = db.get(ReportRecord, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportStatus(
        report_id=report.id,
        status=report.status,
        progress=report.progress,
        current_step=report.current_step,
        error=report.error,
    )


@router.get("/reports/{report_id}/result", response_model=ReportResult)
def get_report(report_id: str, db: Session = Depends(get_db)) -> ReportResult:
    result = get_report_result(db, report_id)
    if not result:
        raise HTTPException(status_code=404, detail="Report not found")
    return result


@router.post("/reports/{report_id}/comment", response_model=CommentResponse)
def comment_preview(
    report_id: str,
    payload: CommentRequest,
    db: Session = Depends(get_db),
) -> CommentResponse:
    report = db.get(ReportRecord, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    markdown = report.github_comment_markdown or "_Report is not ready yet._"
    return CommentResponse(posted=False, dry_run=payload.dry_run, markdown=markdown)
