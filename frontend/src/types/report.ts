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

export interface ReportSummaryItem {
  report_id: string;
  pr_url: string;
  mode: Mode | string;
  status: string;
  progress: number;
  current_step: string;
  title?: string | null;
  owner?: string | null;
  repo?: string | null;
  pull_number?: number | null;
  finding_count: number;
  high_risk_file_count: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  duration_seconds?: number | null;
  retry_of?: string | null;
  error?: string | null;
}

export type QaType = "qa" | "fix_request" | "test_gen";

export interface QaRequest {
  question: string;
  qa_type: QaType;
  context_file?: string;
  context_line_start?: number;
  context_line_end?: number;
  image_urls?: string[];
}

export interface QaResponse {
  answer: string;
  report_id: string;
  message_id: string;
}

export interface ChatHistoryItem {
  message_id: string;
  role: string;
  content: string;
  message_type: string;
  context_file?: string;
  context_line?: number;
  created_at: string;
}
