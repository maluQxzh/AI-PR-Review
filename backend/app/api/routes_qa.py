from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db.models import ChatMessageRecord, ReportRecord
from app.db.session import SessionLocal, get_db
from app.llm.openai_provider import OpenAICompatibleProvider
from app.models.schemas import (
    ChatHistoryItem,
    QaRequest,
    QaResponse,
    QaType,
)

router = APIRouter(prefix="/api", tags=["qa"])

MAX_CONTEXT_FINDINGS = 15
MAX_CONTEXT_FILES = 15


def _build_report_context(report: ReportRecord) -> dict:
    summary = report.summary or {}
    pr_data = report.pr_data or {}
    files = sorted(report.files or [], key=lambda f: f.risk_score or 0, reverse=True)
    findings = sorted(report.findings or [], key=lambda f: f.severity or "P3")

    return {
        "pr": {
            "owner": report.owner,
            "repo": report.repo,
            "number": report.pull_number,
            "title": report.title,
            "description": pr_data.get("description"),
        },
        "summary": {
            "what_changed": summary.get("what_changed", ""),
            "risk_overview": summary.get("risk_overview", ""),
            "review_focus": summary.get("review_focus", []),
        },
        "file_risks": [
            {
                "filename": f.filename,
                "risk_level": f.risk_level,
                "risk_score": f.risk_score,
                "risk_reasons": f.risk_reasons,
                "patch": (f.patch or "")[:3000],
            }
            for f in files[:MAX_CONTEXT_FILES]
        ],
        "findings": [
            {
                "title": f.title,
                "severity": f.severity,
                "confidence": f.confidence,
                "category": f.category,
                "file": f.file,
                "line": f.line,
                "evidence": f.evidence,
                "impact": f.impact,
                "suggestion": f.suggestion,
            }
            for f in findings[:MAX_CONTEXT_FINDINGS]
        ],
    }


def _generate_suggestions(report: ReportRecord) -> list[str]:
    suggestions: list[str] = []
    findings = sorted(report.findings or [], key=lambda f: f.severity or "P3")
    files = sorted(report.files or [], key=lambda f: f.risk_score or 0, reverse=True)

    suggestions.append("这个 PR 的整体风险是什么？")
    suggestions.append("哪些文件最需要关注，为什么？")

    if findings:
        top = findings[0]
        suggestions.append(
            f"为什么 `{top.file}:{top.line}` 的 {top.title} 被评为 {top.severity}？"
        )
        suggestions.append(f"能不能帮我写一个修复 `{top.title}` 的代码？")

    if files:
        high_risk = [f for f in files if f.risk_level in ("critical", "high")]
        target = high_risk[0] if high_risk else files[0]
        suggestions.append(f"为 `{target.filename}` 的改动生成单元测试")

    has_test_file = any("test" in (f.filename or "").lower() for f in files)
    if not has_test_file:
        suggestions.append("这个 PR 的测试覆盖足够吗？哪里需要补充测试？")

    return suggestions[:6]


@router.post("/reports/{report_id}/qa", response_model=QaResponse)
async def ask_question(
    report_id: str,
    payload: QaRequest,
    db: Session = Depends(get_db),
) -> QaResponse:
    report = (
        db.query(ReportRecord)
        .options(
            joinedload(ReportRecord.files),
            joinedload(ReportRecord.findings),
            joinedload(ReportRecord.chat_messages),
        )
        .filter(ReportRecord.id == report_id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "completed":
        raise HTTPException(status_code=400, detail="Report is not completed yet")

    report_context = _build_report_context(report)

    target = None
    if payload.context_file:
        target = {"file": payload.context_file}
        if payload.context_line_start:
            target["line_start"] = payload.context_line_start
        if payload.context_line_end:
            target["line_end"] = payload.context_line_end
        # Attach full patch for this file if available
        for f in report.files:
            if f.filename == payload.context_file and f.patch:
                target["patch"] = f.patch[:5000]
                break
        # Attach related findings for this file
        target["findings"] = [
            {
                "title": f.title,
                "severity": f.severity,
                "line": f.line,
                "evidence": f.evidence,
                "impact": f.impact,
                "suggestion": f.suggestion,
            }
            for f in (report.findings or [])
            if f.file == payload.context_file
        ]

    conversation_history = [
        {"role": m.role, "content": m.content}
        for m in (report.chat_messages or [])
    ]

    provider = OpenAICompatibleProvider()
    answer = await provider.qa(
        question=payload.question,
        report_context=report_context,
        conversation_history=conversation_history,
        qa_type=payload.qa_type.value,
        target=target,
        image_urls=payload.image_urls,
    )

    if answer is None:
        raise HTTPException(status_code=503, detail="LLM not configured")

    # Persist user message
    user_msg = ChatMessageRecord(
        report_id=report_id,
        role="user",
        content=payload.question,
        message_type=payload.qa_type.value,
        context_file=payload.context_file,
        context_line=payload.context_line_start,
    )
    db.add(user_msg)

    # Persist assistant message
    assistant_msg = ChatMessageRecord(
        report_id=report_id,
        role="assistant",
        content=answer,
        message_type=payload.qa_type.value,
        context_file=payload.context_file,
        context_line=payload.context_line_start,
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    return QaResponse(
        answer=answer,
        report_id=report_id,
        message_id=assistant_msg.id,
    )


@router.get("/reports/{report_id}/qa/history", response_model=list[ChatHistoryItem])
def get_qa_history(
    report_id: str,
    db: Session = Depends(get_db),
) -> list[ChatHistoryItem]:
    report = db.query(
        ReportRecord.id
    ).filter(ReportRecord.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    messages = (
        db.query(ChatMessageRecord)
        .filter(ChatMessageRecord.report_id == report_id)
        .order_by(ChatMessageRecord.created_at.asc())
        .all()
    )
    return [
        ChatHistoryItem(
            message_id=m.id,
            role=m.role,
            content=m.content,
            message_type=m.message_type or "qa",
            context_file=m.context_file,
            context_line=m.context_line,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]


@router.get("/reports/{report_id}/qa/suggestions", response_model=list[str])
def get_suggestions(
    report_id: str,
    db: Session = Depends(get_db),
) -> list[str]:
    report = (
        db.query(ReportRecord)
        .options(
            joinedload(ReportRecord.files),
            joinedload(ReportRecord.findings),
        )
        .filter(ReportRecord.id == report_id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return _generate_suggestions(report)
