from fastapi import APIRouter

from app.demo_data import DEMO_REPORT

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/demo-report")
def demo_report() -> dict:
    return DEMO_REPORT
