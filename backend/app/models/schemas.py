from typing import Literal

from pydantic import BaseModel, Field


Mode = Literal["fast", "standard", "deep"]


class AnalyzePrRequest(BaseModel):
    pr_url: str
    mode: Mode = "standard"
    post_comment: bool = False


class AnalyzePrResponse(BaseModel):
    report_id: str
    status: str


class ReportStatus(BaseModel):
    report_id: str
    status: str
    progress: int
    current_step: str
    analysis_detail: str | None = None
    error: str | None = None


class PrInfo(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    description: str | None = None
    author: str | None = None
    base_branch: str | None = None
    head_branch: str | None = None
    html_url: str | None = None
    commits: list[dict] = Field(default_factory=list)


class ChangedFile(BaseModel):
    filename: str
    status: str
    additions: int = 0
    deletions: int = 0
    patch: str | None = None
    risk_level: str = "low"
    risk_score: int = 0
    risk_reasons: list[str] = Field(default_factory=list)


class Summary(BaseModel):
    what_changed: str
    risk_overview: str
    review_focus: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    title: str
    severity: Literal["P0", "P1", "P2", "P3"] = "P2"
    confidence: float = Field(ge=0, le=1)
    category: str
    file: str
    line: int
    evidence: str
    impact: str
    suggestion: str
    comment_draft: str


class TestSuggestion(BaseModel):
    title: str
    reason: str
    suggested_case: str


class ReportResult(BaseModel):
    report_id: str
    status: str
    analysis_source: str = "unknown"
    analysis_detail: str | None = None
    pr: PrInfo | None = None
    summary: Summary | None = None
    file_risks: list[ChangedFile] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    test_suggestions: list[TestSuggestion] = Field(default_factory=list)
    github_comment_markdown: str = ""
    error: str | None = None


class CommentRequest(BaseModel):
    comment_type: Literal["summary", "full"] = "summary"
    dry_run: bool = True


class CommentResponse(BaseModel):
    posted: bool
    dry_run: bool
    markdown: str
