import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.analyzer.report_generator import build_comment_by_type
from app.analyzer.service import (
    TERMINAL_STATUSES,
    analyze_report,
    create_report,
    get_report_result,
    list_report_summaries,
)
from app.db.models import ReportRecord
from app.db.session import SessionLocal, get_db
from app.models.schemas import (
    AnalyzePrResponse,
    CommentRequest,
    CommentResponse,
    ReportResult,
    ReportStatus,
    ReportSummaryItem,
)

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports", response_model=list[ReportSummaryItem])
def list_reports(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ReportSummaryItem]:
    return list_report_summaries(db, limit)


@router.get("/reports/{report_id}", response_model=ReportStatus)
def get_report_status(report_id: str, db: Session = Depends(get_db)) -> ReportStatus:
    report = db.get(ReportRecord, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return _to_status(report)


@router.get("/reports/{report_id}/result", response_model=ReportResult)
def get_report(report_id: str, db: Session = Depends(get_db)) -> ReportResult:
    result = get_report_result(db, report_id)
    if not result:
        raise HTTPException(status_code=404, detail="Report not found")
    return result


@router.post("/reports/{report_id}/retry", response_model=AnalyzePrResponse)
def retry_report(
    report_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AnalyzePrResponse:
    report = db.get(ReportRecord, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    retry = create_report(
        db,
        report.pr_url,
        report.mode or "standard",
        retry_of=report.id,
        attempt_count=(report.attempt_count or 1) + 1,
    )
    background_tasks.add_task(analyze_report, retry.id, retry.pr_url, retry.mode)
    return AnalyzePrResponse(report_id=retry.id, status=retry.status)


@router.post("/reports/{report_id}/cancel", response_model=ReportStatus)
def cancel_report(report_id: str, db: Session = Depends(get_db)) -> ReportStatus:
    report = db.get(ReportRecord, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status not in TERMINAL_STATUSES:
        report.cancel_requested = True
        report.current_step = "正在取消"
        db.commit()
        db.refresh(report)
    return _to_status(report)


@router.get("/reports/{report_id}/events")
async def report_events(report_id: str) -> StreamingResponse:
    async def event_stream():
        while True:
            db = SessionLocal()
            try:
                report = db.get(ReportRecord, report_id)
                if not report:
                    payload = {"status": "failed", "error": "Report not found"}
                    yield f"data: {json.dumps(payload)}\n\n"
                    return
                payload = _to_status(report).model_dump()
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if report.status in TERMINAL_STATUSES:
                    return
            finally:
                db.close()
            await asyncio.sleep(0.8)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/reports/{report_id}/comment", response_model=CommentResponse)
def comment_preview(
    report_id: str,
    payload: CommentRequest,
    db: Session = Depends(get_db),
) -> CommentResponse:
    report = db.get(ReportRecord, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    markdown = build_comment_by_type(
        report.github_comment_markdown or "_Report is not ready yet._",
        report.generated_artifacts,
        payload.comment_type,
    )
    return CommentResponse(posted=False, dry_run=payload.dry_run, markdown=markdown)


def _to_status(report: ReportRecord) -> ReportStatus:
    return ReportStatus(
        report_id=report.id,
        status=report.status,
        progress=report.progress,
        current_step=report.current_step,
        analysis_detail=report.analysis_detail,
        completed_at=report.completed_at.isoformat() if report.completed_at else None,
        duration_seconds=report.duration_seconds,
        error=report.error,
    )
