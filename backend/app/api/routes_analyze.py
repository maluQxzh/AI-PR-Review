from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.analyzer.service import analyze_report, create_report
from app.db.session import get_db
from app.models.schemas import AnalyzePrRequest, AnalyzePrResponse

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/analyze-pr", response_model=AnalyzePrResponse)
async def analyze_pr(
    payload: AnalyzePrRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AnalyzePrResponse:
    report = create_report(db, payload.pr_url)
    background_tasks.add_task(analyze_report, report.id, payload.pr_url, payload.mode)
    return AnalyzePrResponse(report_id=report.id, status=report.status)
