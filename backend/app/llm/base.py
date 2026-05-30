from pydantic import BaseModel, Field

from app.models.schemas import Finding, Summary, TestSuggestion


class ReviewOutput(BaseModel):
    source: str = "llm"
    summary: Summary
    findings: list[Finding] = Field(default_factory=list)
    test_suggestions: list[TestSuggestion] = Field(default_factory=list)
