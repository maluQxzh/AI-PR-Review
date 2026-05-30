from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


Mode = Literal["fast", "standard", "deep"]


class QaType(str, Enum):
    qa = "qa"
    fix_request = "fix_request"
    test_gen = "test_gen"


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


class ReportSummaryItem(BaseModel):
    report_id: str
    pr_url: str
    mode: str = "standard"
    status: str
    progress: int
    current_step: str
    title: str | None = None
    owner: str | None = None
    repo: str | None = None
    pull_number: int | None = None
    finding_count: int = 0
    high_risk_file_count: int = 0
    created_at: str
    updated_at: str
    completed_at: str | None = None
    duration_seconds: int | None = None
    retry_of: str | None = None
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
    base_sha: str | None = None
    head_sha: str | None = None
    default_branch: str | None = None
    html_url: str | None = None
    commits: list[dict] = Field(default_factory=list)


class ContextSnippet(BaseModel):
    kind: str
    path: str
    ref: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    language: str = "text"
    content: str = ""
    note: str | None = None


class ChangedFileContext(BaseModel):
    base_ref: str | None = None
    head_ref: str | None = None
    snippets: list[ContextSnippet] = Field(default_factory=list)
    related_tests: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ChangedFile(BaseModel):
    filename: str
    status: str
    additions: int = 0
    deletions: int = 0
    patch: str | None = None
    context: ChangedFileContext | None = None
    risk_level: str = "low"
    risk_score: int = 0
    risk_reasons: list[str] = Field(default_factory=list)
    risk_dimensions: list[str] = Field(default_factory=list)
    # Allowed values: "security", "logic", "concurrency", "compatibility",
    # "performance", "maintainability", "data", "test_gap"


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
    tag: str = ""  # "[建议]" when downgraded; empty string renders as "[问题]"


class TestSuggestion(BaseModel):
    title: str
    reason: str
    suggested_case: str


class ContextSummary(BaseModel):
    available: bool = False
    mode: str = "standard"
    target_files: list[str] = Field(default_factory=list)
    changed_files_with_context: int = 0
    related_tests_checked: list[str] = Field(default_factory=list)
    repository_docs_checked: list[str] = Field(default_factory=list)
    history_items: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReviewContext(BaseModel):
    summary: ContextSummary = Field(default_factory=ContextSummary)
    repository_docs: list[ContextSnippet] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


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
    context_summary: ContextSummary | None = None
    review_context: ReviewContext | None = None
    github_comment_markdown: str = ""
    error: str | None = None


class CommentRequest(BaseModel):
    comment_type: Literal["summary", "full"] = "summary"
    dry_run: bool = True


class CommentResponse(BaseModel):
    posted: bool
    dry_run: bool
    markdown: str


class QaRequest(BaseModel):
    question: str
    qa_type: QaType = QaType.qa
    context_file: str | None = None
    context_line_start: int | None = None
    context_line_end: int | None = None
    image_urls: list[str] | None = None


class QaResponse(BaseModel):
    answer: str
    report_id: str
    message_id: str


class ChatHistoryItem(BaseModel):
    message_id: str
    role: str
    content: str
    message_type: str = "qa"
    context_file: str | None = None
    context_line: int | None = None
    created_at: str
