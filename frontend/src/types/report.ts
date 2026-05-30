export type Mode = "fast" | "standard" | "deep";

export interface PrInfo {
  owner: string;
  repo: string;
  number: number;
  title: string;
  description?: string;
  author?: string;
  base_branch?: string;
  head_branch?: string;
  html_url?: string;
}

export interface Summary {
  what_changed: string;
  risk_overview: string;
  review_focus: string[];
}

export interface FileRisk {
  filename: string;
  status: string;
  additions: number;
  deletions: number;
  patch?: string;
  risk_level: "low" | "medium" | "high" | "critical" | string;
  risk_score: number;
  risk_reasons: string[];
}

export interface Finding {
  title: string;
  severity: "P0" | "P1" | "P2" | "P3";
  confidence: number;
  category: string;
  file: string;
  line: number;
  evidence: string;
  impact: string;
  suggestion: string;
  comment_draft: string;
}

export interface TestSuggestion {
  title: string;
  reason: string;
  suggested_case: string;
}

export interface ReportResult {
  report_id: string;
  status: string;
  analysis_source?: "llm" | "fallback" | "demo" | "unknown" | string;
  pr?: PrInfo;
  summary?: Summary;
  file_risks: FileRisk[];
  findings: Finding[];
  test_suggestions: TestSuggestion[];
  github_comment_markdown: string;
  error?: string;
}

export interface ReportStatus {
  report_id: string;
  status: string;
  progress: number;
  current_step: string;
  error?: string;
}
