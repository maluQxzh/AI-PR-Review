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
  base_sha?: string;
  head_sha?: string;
  default_branch?: string;
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
  context?: ChangedFileContext | null;
  risk_level: "low" | "medium" | "high" | "critical" | string;
  risk_score: number;
  risk_reasons: string[];
}

export interface ContextSnippet {
  kind: string;
  path: string;
  ref?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  language: string;
  content: string;
  note?: string | null;
}

export interface ChangedFileContext {
  base_ref?: string | null;
  head_ref?: string | null;
  snippets: ContextSnippet[];
  related_tests: string[];
  related_files: string[];
  notes: string[];
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

export interface ContextSummary {
  available: boolean;
  mode: string;
  target_files: string[];
  changed_files_with_context: number;
  related_tests_checked: string[];
  repository_docs_checked: string[];
  history_items: Array<Record<string, unknown>>;
  notes: string[];
}

export interface ReviewContext {
  summary: ContextSummary;
  repository_docs: ContextSnippet[];
  history: Array<Record<string, unknown>>;
  notes: string[];
}

export interface ReportResult {
  report_id: string;
  status: string;
  analysis_source?: "llm" | "llm_fast_retry" | "fallback" | "demo" | "unknown" | string;
  analysis_detail?: string | null;
  pr?: PrInfo;
  summary?: Summary;
  file_risks: FileRisk[];
  findings: Finding[];
  test_suggestions: TestSuggestion[];
  context_summary?: ContextSummary | null;
  review_context?: ReviewContext | null;
  github_comment_markdown: string;
  error?: string;
}

export interface ReportStatus {
  report_id: string;
  status: string;
  progress: number;
  current_step: string;
  analysis_detail?: string | null;
  error?: string;
}
