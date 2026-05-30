import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  ExternalLink,
  FileCode2,
  GitPullRequest,
  History,
  Loader2,
  Play,
  RefreshCw,
  ShieldAlert,
  TestTube2,
  XCircle,
} from "lucide-react";
import {
  analyzePr,
  cancelReport,
  getDemoReport,
  getReport,
  getStatus,
  listReports,
  reportEventsUrl,
  retryReport,
} from "./api/client";
import type { FileRisk, Finding, Mode, ReportResult, ReportStatus, ReportSummaryItem } from "./types/report";
import "./styles.css";

type SeverityFilter = "all" | "P0" | "P1" | "P2" | "P3";
type RiskFilter = "all" | "critical" | "high" | "medium" | "low";

const terminalStatuses = new Set(["completed", "failed", "cancelled"]);

function App() {
  const [prUrl, setPrUrl] = useState("");
  const [mode, setMode] = useState<Mode>("standard");
  const [status, setStatus] = useState("准备就绪");
  const [progress, setProgress] = useState(0);
  const [report, setReport] = useState<ReportResult | null>(null);
  const [currentReportId, setCurrentReportId] = useState<string | null>(null);
  const [history, setHistory] = useState<ReportSummaryItem[]>([]);
  const [error, setError] = useState("");
  const [analysisDetail, setAnalysisDetail] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    refreshHistory();
    return () => eventSourceRef.current?.close();
  }, []);

  async function refreshHistory() {
    try {
      setHistory(await listReports());
    } catch {
      setHistory([]);
    }
  }

  async function runAnalysis(nextUrl = prUrl, nextMode = mode) {
    if (!nextUrl.trim()) {
      return;
    }
    setError("");
    setAnalysisDetail("");
    setElapsedSeconds(0);
    setReport(null);
    setStatus("正在创建分析任务");
    setProgress(5);
    setIsRunning(true);
    try {
      const task = await analyzePr(nextUrl, nextMode);
      setCurrentReportId(task.report_id);
      await watchReport(task.report_id);
    } catch (err) {
      failWith(err);
    } finally {
      setIsRunning(false);
      refreshHistory();
    }
  }

  async function retryCurrentReport() {
    if (!currentReportId) {
      return;
    }
    setError("");
    setAnalysisDetail("");
    setElapsedSeconds(0);
    setReport(null);
    setStatus("正在创建重试任务");
    setProgress(5);
    setIsRunning(true);
    try {
      const task = await retryReport(currentReportId);
      setCurrentReportId(task.report_id);
      await watchReport(task.report_id);
    } catch (err) {
      failWith(err);
    } finally {
      setIsRunning(false);
      refreshHistory();
    }
  }

  async function cancelCurrentReport() {
    if (!currentReportId) {
      return;
    }
    try {
      const next = await cancelReport(currentReportId);
      applyStatus(next);
      setIsRunning(next.status !== "cancelled");
    } catch (err) {
      failWith(err);
    }
  }

  async function loadHistoryReport(reportId: string) {
    eventSourceRef.current?.close();
    setError("");
    setIsRunning(false);
    setCurrentReportId(reportId);
    try {
      const selected = await getReport(reportId);
      setReport(selected);
      setStatus(statusLabel(selected.status));
      setProgress(selected.status === "completed" ? 100 : 0);
      setAnalysisDetail(selected.analysis_detail ?? "");
      if (selected.pr?.html_url) {
        setPrUrl(selected.pr.html_url);
      }
    } catch (err) {
      failWith(err);
    }
  }

  async function loadDemo() {
    eventSourceRef.current?.close();
    setError("");
    setAnalysisDetail("");
    setElapsedSeconds(0);
    setIsRunning(false);
    setCurrentReportId("demo-report");
    setStatus("已加载离线演示报告");
    setProgress(100);
    const demo = await getDemoReport();
    setReport(demo);
    if (demo.pr?.html_url) {
      setPrUrl(demo.pr.html_url);
    }
  }

  async function watchReport(reportId: string) {
    const startedAt = Date.now();
    eventSourceRef.current?.close();

    await new Promise<void>((resolve, reject) => {
      let settled = false;
      let fallbackStarted = false;
      const events = new EventSource(reportEventsUrl(reportId));
      eventSourceRef.current = events;

      const finish = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };

      const fallbackToPolling = async () => {
        if (fallbackStarted || settled) {
          return;
        }
        fallbackStarted = true;
        events.close();
        try {
          await pollReport(reportId, startedAt);
          finish();
        } catch (err) {
          if (!settled) {
            settled = true;
            reject(err);
          }
        }
      };

      events.onmessage = async (event) => {
        const next = JSON.parse(event.data) as ReportStatus;
        setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
        applyStatus(next);
        if (next.status === "completed") {
          events.close();
          const completed = await getReport(reportId);
          setAnalysisDetail(completed.analysis_detail ?? next.analysis_detail ?? "");
          setReport(completed);
          finish();
        }
        if (next.status === "failed") {
          events.close();
          setReport(null);
          if (!settled) {
            settled = true;
            reject(new Error(next.error ?? "Analysis failed"));
          }
        }
        if (next.status === "cancelled") {
          events.close();
          finish();
        }
      };

      events.onerror = fallbackToPolling;
    });
  }

  async function pollReport(reportId: string, startedAt: number) {
    for (let attempt = 0; attempt < 420; attempt += 1) {
      const next = await getStatus(reportId);
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
      applyStatus(next);
      if (next.status === "completed") {
        const completed = await getReport(reportId);
        setAnalysisDetail(completed.analysis_detail ?? next.analysis_detail ?? "");
        setReport(completed);
        return;
      }
      if (next.status === "failed") {
        throw new Error(next.error ?? "Analysis failed");
      }
      if (next.status === "cancelled") {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
    throw new Error("等待分析结果超时。");
  }

  function applyStatus(next: ReportStatus) {
    setStatus(next.current_step);
    setProgress(next.progress);
    setAnalysisDetail(next.analysis_detail ?? "");
  }

  function failWith(err: unknown) {
    setError(err instanceof Error ? err.message : "未知错误");
    setStatus("分析失败");
    setProgress(100);
  }

  const canReanalyze = Boolean(prUrl.trim()) && !isRunning;
  const canRetry = Boolean(currentReportId && currentReportId !== "demo-report") && !isRunning;

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <div className="eyebrow">
            <GitPullRequest size={16} />
            AI PR Review 助手
          </div>
          <h1>Pull Request 风险分析与评审建议</h1>
        </div>
        <button className="ghostButton" onClick={loadDemo}>
          <FileCode2 size={18} />
          加载演示
        </button>
      </section>

      <section className="workbench">
        <div className="inputPanel">
          <label htmlFor="pr-url">GitHub PR 地址</label>
          <div className="urlRow">
            <input
              id="pr-url"
              value={prUrl}
              onChange={(event) => setPrUrl(event.target.value)}
              placeholder="https://github.com/owner/repo/pull/123"
            />
            <button onClick={() => runAnalysis()} disabled={!prUrl.trim() || isRunning}>
              {isRunning ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
              开始分析
            </button>
          </div>
          <div className="modeRow" aria-label="Analysis mode">
            {(["fast", "standard", "deep"] as Mode[]).map((item) => (
              <button
                key={item}
                className={mode === item ? "mode active" : "mode"}
                onClick={() => setMode(item)}
                disabled={isRunning}
              >
                {modeLabel(item)}
              </button>
            ))}
          </div>
          <div className="actionRow">
            <button className="secondaryButton" onClick={() => runAnalysis()} disabled={!canReanalyze}>
              <RefreshCw size={16} />
              重新分析
            </button>
            <button className="secondaryButton" onClick={retryCurrentReport} disabled={!canRetry}>
              <RefreshCw size={16} />
              失败重试
            </button>
            <button className="dangerButton" onClick={cancelCurrentReport} disabled={!isRunning || !currentReportId}>
              <XCircle size={16} />
              取消
            </button>
          </div>
          <div className="progressBlock">
            <div className="statusText">
              {isRunning ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
              {status}
            </div>
            <div className="progressTrack">
              <div style={{ width: `${progress}%` }} />
            </div>
            {isRunning && <div className="detailText">已等待 {elapsedSeconds}s</div>}
            {analysisDetail && <div className="detailText">{analysisDetail}</div>}
          </div>
          {error && <div className="errorBox">{error}</div>}
          <HistoryList history={history} activeReportId={currentReportId} onSelect={loadHistoryReport} />
        </div>

        {report ? <ReportView report={report} /> : <EmptyState />}
      </section>
    </main>
  );
}

function EmptyState() {
  return (
    <section className="emptyState">
      <ShieldAlert size={38} />
      <h2>准备开始评审</h2>
      <p>输入公开 GitHub PR 地址，或加载离线演示报告查看完整流程。</p>
    </section>
  );
}

function HistoryList({
  history,
  activeReportId,
  onSelect,
}: {
  history: ReportSummaryItem[];
  activeReportId: string | null;
  onSelect: (reportId: string) => void;
}) {
  if (history.length === 0) {
    return null;
  }
  return (
    <section className="historyBlock">
      <div className="historyTitle">
        <History size={16} />
        最近分析
      </div>
      <div className="historyList">
        {history.map((item) => (
          <button
            key={item.report_id}
            className={item.report_id === activeReportId ? "historyItem active" : "historyItem"}
            onClick={() => onSelect(item.report_id)}
          >
            <span>{item.title ?? item.pr_url}</span>
            <small>
              {statusLabel(item.status)} · {item.finding_count} findings · {item.high_risk_file_count} 高风险文件
            </small>
          </button>
        ))}
      </div>
    </section>
  );
}

function ReportView({ report }: { report: ReportResult }) {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const highRiskCount = report.file_risks.filter((file) => ["critical", "high"].includes(file.risk_level)).length;
  const filteredFindings = useMemo(
    () =>
      severityFilter === "all"
        ? report.findings
        : report.findings.filter((finding) => finding.severity === severityFilter),
    [report.findings, severityFilter],
  );
  const filteredFiles = useMemo(
    () =>
      riskFilter === "all"
        ? report.file_risks
        : report.file_risks.filter((file) => file.risk_level === riskFilter),
    [report.file_risks, riskFilter],
  );

  return (
    <section className="reportGrid">
      <article className="summaryPanel">
        <div className="panelTitle">
          <GitPullRequest size={18} />
          {report.pr ? `${report.pr.owner}/${report.pr.repo}#${report.pr.number}` : report.report_id}
        </div>
        <h2>{report.pr?.title ?? "分析报告"}</h2>
        <p>{report.summary?.what_changed}</p>
        <div className="metricRow">
          <Metric label="问题数" value={report.findings.length.toString()} />
          <Metric label="高风险文件" value={highRiskCount.toString()} />
          <Metric label="测试建议" value={report.test_suggestions.length.toString()} />
        </div>
        <div className={`sourceBadge ${report.analysis_source ?? "unknown"}`}>
          分析来源：{sourceLabel(report.analysis_source)}
        </div>
        {report.analysis_detail && <p className="sourceDetail">{report.analysis_detail}</p>}
        <div className="focusRow">
          {report.summary?.review_focus.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      </article>

      <article className="panel">
        <div className="panelTitle">
          <AlertTriangle size={18} />
          风险概览
        </div>
        <p className="muted">{report.summary?.risk_overview}</p>
        <SegmentedFilter
          label="风险级别"
          value={riskFilter}
          options={["all", "critical", "high", "medium", "low"]}
          onChange={(value) => setRiskFilter(value as RiskFilter)}
        />
        <div className="fileList">
          {filteredFiles.map((file) => (
            <FileRiskRow key={file.filename} file={file} />
          ))}
          {filteredFiles.length === 0 && <p className="muted">当前筛选条件下没有风险文件。</p>}
        </div>
      </article>

      <article className="panel findingsPanel">
        <div className="panelTitle">
          <ShieldAlert size={18} />
          评审问题
        </div>
        <SegmentedFilter
          label="严重级别"
          value={severityFilter}
          options={["all", "P0", "P1", "P2", "P3"]}
          onChange={(value) => setSeverityFilter(value as SeverityFilter)}
        />
        <div className="findingList">
          {filteredFindings.map((finding) => (
            <FindingCard key={`${finding.file}:${finding.line}:${finding.title}`} finding={finding} prUrl={report.pr?.html_url} />
          ))}
          {filteredFindings.length === 0 && <p className="muted">当前筛选条件下没有评审问题。</p>}
        </div>
      </article>

      <article className="panel">
        <div className="panelTitle">
          <TestTube2 size={18} />
          测试建议
        </div>
        {report.test_suggestions.map((item) => (
          <div className="testItem" key={item.title}>
            <strong>{item.title}</strong>
            <p>{item.reason}</p>
            <code>{item.suggested_case}</code>
          </div>
        ))}
      </article>

      <article className="panel markdownPanel">
        <div className="panelTitle">
          <Clipboard size={18} />
          GitHub 评论预览
        </div>
        <button className="copyButton" onClick={() => navigator.clipboard.writeText(report.github_comment_markdown)}>
          <Clipboard size={16} />
          复制
        </button>
        <pre>{report.github_comment_markdown}</pre>
      </article>
    </section>
  );
}

function SegmentedFilter({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="filterBlock">
      <span>{label}</span>
      <div className="filterRow">
        {options.map((option) => (
          <button key={option} className={value === option ? "filter active" : "filter"} onClick={() => onChange(option)}>
            {option === "all" ? "All" : option}
          </button>
        ))}
      </div>
    </div>
  );
}

function FileRiskRow({ file }: { file: FileRisk }) {
  return (
    <details className={`fileRisk ${file.risk_level}`}>
      <summary>
        <span>{file.filename}</span>
        <b>{file.risk_score}</b>
      </summary>
      <div className="reasonList">
        {file.risk_reasons.map((reason) => (
          <span key={reason}>{reason}</span>
        ))}
      </div>
      {file.patch && <pre className="patchBlock">{file.patch}</pre>}
    </details>
  );
}

function FindingCard({ finding, prUrl }: { finding: Finding; prUrl?: string }) {
  const filesUrl = prUrl ? `${prUrl.replace(/\/$/, "")}/files` : "";
  const inlineComment = `**${finding.severity} ${finding.title}**\n\nFile: \`${finding.file}:${finding.line}\`\n\n${finding.comment_draft}`;
  return (
    <div className={`finding ${finding.severity}`}>
      <div className="findingHead">
        <span>{finding.severity}</span>
        <strong>{finding.title}</strong>
        <small>{Math.round(finding.confidence * 100)}%</small>
      </div>
      <code>
        {finding.file}:{finding.line}
      </code>
      <p>{finding.evidence}</p>
      <p>{finding.impact}</p>
      <p>{finding.suggestion}</p>
      <div className="findingActions">
        <button className="copyButton" onClick={() => navigator.clipboard.writeText(inlineComment)}>
          <Clipboard size={16} />
          复制单条评论
        </button>
        {filesUrl && (
          <a className="linkButton" href={filesUrl} target="_blank" rel="noreferrer">
            <ExternalLink size={16} />
            GitHub 行
          </a>
        )}
      </div>
    </div>
  );
}

function sourceLabel(source?: string) {
  if (source === "llm") {
    return "LLM API";
  }
  if (source === "llm_fast_retry") {
    return "LLM API（快模型重试）";
  }
  if (source === "fallback") {
    return "规则降级";
  }
  if (source === "demo") {
    return "离线演示";
  }
  return "未知";
}

function modeLabel(nextMode: Mode) {
  if (nextMode === "fast") {
    return "快速";
  }
  if (nextMode === "deep") {
    return "深度";
  }
  return "标准";
}

function statusLabel(nextStatus: string) {
  if (nextStatus === "completed") {
    return "已完成";
  }
  if (nextStatus === "failed") {
    return "失败";
  }
  if (nextStatus === "cancelled") {
    return "已取消";
  }
  if (nextStatus === "running") {
    return "运行中";
  }
  return "排队中";
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
