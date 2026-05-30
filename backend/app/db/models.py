from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def uuid_str() -> str:
    return str(uuid4())


class ReportRecord(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    pr_url: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    repo: Mapped[str | None] = mapped_column(String, nullable=True)
    pull_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String, default="standard")
    status: Mapped[str] = mapped_column(String, default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str] = mapped_column(String, default="Queued")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_of: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pr_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    context_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    test_suggestions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    generated_artifacts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_source: Mapped[str | None] = mapped_column(String, nullable=True)
    analysis_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_comment_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    files: Mapped[list["ChangedFileRecord"]] = relationship(
        cascade="all, delete-orphan", back_populates="report"
    )
    findings: Mapped[list["FindingRecord"]] = relationship(
        cascade="all, delete-orphan", back_populates="report"
    )


class ChangedFileRecord(Base):
    __tablename__ = "changed_files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"))
    filename: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    patch: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_level: Mapped[str] = mapped_column(String, default="low")
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_reasons: Mapped[list] = mapped_column(JSON, default=list)
    risk_dimensions: Mapped[list] = mapped_column(JSON, default=list)

    report: Mapped[ReportRecord] = relationship(back_populates="files")


class FindingRecord(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"))
    file: Mapped[str] = mapped_column(Text)
    line: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text)
    comment_draft: Mapped[str] = mapped_column(Text)

    report: Mapped[ReportRecord] = relationship(back_populates="findings")


class ReviewFeedbackRecord(Base):
    __tablename__ = "review_feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    user_action: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
