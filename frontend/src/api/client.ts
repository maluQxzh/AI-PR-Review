import type { ChatHistoryItem, Mode, QaRequest, QaResponse, ReportResult, ReportStatus, ReportSummaryItem } from "../types/report";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export function reportEventsUrl(reportId: string) {
  return `${API_BASE}/api/reports/${reportId}/events`;
}

export async function analyzePr(prUrl: string, mode: Mode) {
  const response = await fetch(`${API_BASE}/api/analyze-pr`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pr_url: prUrl, mode, post_comment: false }),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as { report_id: string; status: string };
}

export async function getStatus(reportId: string) {
  const response = await fetch(`${API_BASE}/api/reports/${reportId}`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as ReportStatus;
}

export async function getReport(reportId: string) {
  const response = await fetch(`${API_BASE}/api/reports/${reportId}/result`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as ReportResult;
}

export async function listReports() {
  const response = await fetch(`${API_BASE}/api/reports`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as ReportSummaryItem[];
}

export async function retryReport(reportId: string) {
  const response = await fetch(`${API_BASE}/api/reports/${reportId}/retry`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as { report_id: string; status: string };
}

export async function cancelReport(reportId: string) {
  const response = await fetch(`${API_BASE}/api/reports/${reportId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as ReportStatus;
}

export async function getDemoReport() {
  try {
    const response = await fetch(`${API_BASE}/api/demo-report`);
    if (response.ok) {
      return (await response.json()) as ReportResult;
    }
  } catch {
    // Local fallback below keeps the demo usable when the backend is not running.
  }
  const module = await import("../data/demoReport");
  return module.demoReport;
}

export async function askQuestion(reportId: string, payload: QaRequest) {
  const response = await fetch(`${API_BASE}/api/reports/${reportId}/qa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as QaResponse;
}

export async function getQaHistory(reportId: string) {
  const response = await fetch(`${API_BASE}/api/reports/${reportId}/qa/history`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as ChatHistoryItem[];
}

export async function getQaSuggestions(reportId: string) {
  const response = await fetch(`${API_BASE}/api/reports/${reportId}/qa/suggestions`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as string[];
}
