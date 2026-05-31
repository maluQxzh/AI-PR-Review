import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  Bug,
  CheckCircle2,
  Clipboard,
  ExternalLink,
  FileCode2,
  GitPullRequest,
  History,
  Lightbulb,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  ShieldAlert,
  Send,
  Tags,
  TestTube2,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  analyzePr,
  askQuestion,
  cancelReport,
  getDemoReport,
  getQaHistory,
  getQaSuggestions,
  getReport,
  getStatus,
  listReports,
  reportEventsUrl,
  retryReport,
} from "./api/client";
import type { ChatHistoryItem, FileRisk, Finding, GeneratedArtifacts, Mode, QaType, ReportResult, ReportStatus, ReportSummaryItem } from "./types/report";
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
      setStatus(selected.status === "completed" ? completedStatusText(selected.duration_seconds) : statusLabel(selected.status));
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
    setProgress(100);
    const demo = await getDemoReport();
    setReport(demo);
    setStatus(completedStatusText(demo.duration_seconds, "已加载离线演示报告"));
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
          setStatus(completedStatusText(completed.duration_seconds ?? next.duration_seconds));
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
        setStatus(completedStatusText(completed.duration_seconds ?? next.duration_seconds));
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
    setStatus(next.status === "completed" ? completedStatusText(next.duration_seconds) : next.current_step);
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
              {item.status === "completed" ? completedStatusText(item.duration_seconds) : statusLabel(item.status)} ·{" "}
              {item.finding_count} findings · {item.high_risk_file_count} 高风险文件
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
  const [prefillQuestion, setPrefillQuestion] = useState("");
  const [prefillQaType, setPrefillQaType] = useState<QaType>("qa");
  const [prefillFile, setPrefillFile] = useState<string | undefined>(undefined);
  const [prefillLineStart, setPrefillLineStart] = useState<number | undefined>(undefined);
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

  function handleAskFinding(finding: Finding, qaType: QaType) {
    if (qaType === "qa") {
      setPrefillQuestion(`\`${finding.file}:${finding.line}\` 的 ${finding.title} 有什么问题？`);
    } else if (qaType === "fix_request") {
      setPrefillQuestion(`请帮我写一个修复 \`${finding.file}:${finding.line}\` ${finding.title} 的代码`);
    } else {
      setPrefillQuestion(`为 \`${finding.file}:${finding.line}\` 的 ${finding.title} 生成单元测试`);
    }
    setPrefillQaType(qaType);
    setPrefillFile(finding.file);
    setPrefillLineStart(finding.line);
  }

  function handleAskFile(filename: string) {
    setPrefillQuestion(`\`${filename}\` 有哪些风险？具体在哪些代码行？`);
    setPrefillQaType("qa");
    setPrefillFile(filename);
    setPrefillLineStart(undefined);
  }

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

      {report.context_summary && <ContextPanel report={report} />}

      {report.generated_artifacts && <PrPreparationPanel artifacts={report.generated_artifacts} />}

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
            <FileRiskRow key={file.filename} file={file} onAsk={() => handleAskFile(file.filename)} />
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
            <FindingCard key={`${finding.file}:${finding.line}:${finding.title}`} finding={finding} prUrl={report.pr?.html_url} onAsk={(qaType) => handleAskFinding(finding, qaType)} />
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

      {report.generated_artifacts && <ImprovementsPanel artifacts={report.generated_artifacts} />}

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

      <ChatPanel
        reportId={report.report_id}
        prefillQuestion={prefillQuestion}
        prefillQaType={prefillQaType}
        prefillFile={prefillFile}
        prefillLineStart={prefillLineStart}
        onPrefillConsumed={() => { setPrefillQuestion(""); setPrefillFile(undefined); setPrefillLineStart(undefined); }}
      />
    </section>
  );
}

function ContextPanel({ report }: { report: ReportResult }) {
  const summary = report.context_summary;
  if (!summary) {
    return null;
  }
  const notes = summary.notes.filter(Boolean);
  return (
    <article className="panel contextPanel">
      <div className="panelTitle">
        <FileCode2 size={18} />
        上下文覆盖
      </div>
      <div className="contextStats">
        <Metric label="目标文件" value={summary.target_files.length.toString()} />
        <Metric label="有上下文" value={summary.changed_files_with_context.toString()} />
        <Metric label="历史线索" value={summary.history_items.length.toString()} />
      </div>
      <ContextList title="相关测试" items={summary.related_tests_checked} />
      <ContextList title="仓库约定" items={summary.repository_docs_checked} />
      {notes.length > 0 && <ContextList title="降级说明" items={notes} />}
      {report.generated_artifacts?.similar_items.length ? (
        <div className="similarList">
          <strong>相似 Issue / PR</strong>
          {report.generated_artifacts.similar_items.slice(0, 6).map((item) => (
            <a key={item.html_url} href={item.html_url} target="_blank" rel="noreferrer">
              <span>{item.kind === "pull_request" ? "PR" : "Issue"} · {item.state}</span>
              <b>{item.title}</b>
              <small>{item.relevance_reason}</small>
            </a>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function PrPreparationPanel({ artifacts }: { artifacts: GeneratedArtifacts }) {
  const labelsText = artifacts.pr_metadata.labels.map((item) => item.name).join(", ");
  return (
    <article className="panel prepPanel">
      <div className="panelTitle">
        <Tags size={18} />
        PR 准备
      </div>
      <div className="prepHeader">
        <div>
          <span>建议标题</span>
          <strong>{artifacts.pr_metadata.suggested_title}</strong>
        </div>
        <code>{artifacts.pr_metadata.pr_type}</code>
      </div>
      <div className="labelCloud">
        {artifacts.pr_metadata.labels.map((label) => (
          <span key={label.name} title={`${label.reason} · ${Math.round(label.confidence * 100)}%`}>
            {label.name}
          </span>
        ))}
      </div>
      <div className="walkthroughList">
        {artifacts.pr_description.walkthrough.map((item) => (
          <div key={`${item.area}:${item.files.join(",")}`}>
            <strong>{item.area}</strong>
            <p>{item.description}</p>
            <small>{item.files.slice(0, 5).join(", ")}</small>
          </div>
        ))}
      </div>
      {artifacts.changelog && (
        <div className="changelogBox">
          <strong>Changelog</strong>
          <p>{artifacts.changelog.entry}</p>
          <button className="copyButton" onClick={() => navigator.clipboard.writeText(artifacts.changelog?.entry ?? "")}>
            <Clipboard size={16} />
            复制
          </button>
        </div>
      )}
      <div className="markdownDraft">
        <button className="copyButton" onClick={() => navigator.clipboard.writeText(artifacts.pr_description.markdown)}>
          <Clipboard size={16} />
          复制 PR 描述
        </button>
        <button className="copyButton" onClick={() => navigator.clipboard.writeText(labelsText)}>
          <Clipboard size={16} />
          复制 Labels
        </button>
        <pre>{artifacts.pr_description.markdown}</pre>
      </div>
    </article>
  );
}

function ImprovementsPanel({ artifacts }: { artifacts: GeneratedArtifacts }) {
  const hasImprovements = artifacts.code_improvements.length > 0;
  const hasDocs = artifacts.documentation_suggestions.length > 0;
  if (!hasImprovements && !hasDocs) {
    return null;
  }
  return (
    <article className="panel improvementsPanel">
      <div className="panelTitle">
        <Lightbulb size={18} />
        改进建议
      </div>
      {artifacts.code_improvements.map((item) => (
        <div className="improvementItem" key={`${item.file}:${item.line ?? "file"}:${item.title}`}>
          <div>
            <strong>{item.title}</strong>
            <small>{item.category} · {Math.round(item.confidence * 100)}%</small>
          </div>
          <code>{item.file}{item.line ? `:${item.line}` : ""}</code>
          <p>{item.reason}</p>
          <p>{item.suggestion}</p>
        </div>
      ))}
      {artifacts.documentation_suggestions.map((item) => (
        <div className="docSuggestion" key={`${item.target}:${item.proposed_text}`}>
          <strong>{item.target}</strong>
          <p>{item.reason}</p>
          <code>{item.proposed_text}</code>
        </div>
      ))}
    </article>
  );
}

function ContextList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="contextList">
      <strong>{title}</strong>
      <div>
        {items.slice(0, 8).map((item) => (
          <code key={item}>{item}</code>
        ))}
      </div>
    </div>
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

function FileRiskRow({ file, onAsk }: { file: FileRisk; onAsk?: () => void }) {
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
      {onAsk && (
        <button className="askButton" onClick={(e) => { e.preventDefault(); onAsk(); }}>
          <MessageSquare size={14} />
          追问此文件
        </button>
      )}
    </details>
  );
}

function FindingCard({ finding, prUrl, onAsk }: { finding: Finding; prUrl?: string; onAsk?: (qaType: QaType) => void }) {
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
      {onAsk && (
        <div className="askRow">
          <button className="askButton" onClick={() => onAsk("qa")}>
            <MessageSquare size={14} />
            追问
          </button>
          <button className="askButton" onClick={() => onAsk("fix_request")}>
            <Wrench size={14} />
            修代码
          </button>
          <button className="askButton" onClick={() => onAsk("test_gen")}>
            <Bug size={14} />
            写测试
          </button>
        </div>
      )}
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
    return "分析完成";
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

function completedStatusText(durationSeconds?: number | null, fallback = "分析完成") {
  if (typeof durationSeconds !== "number" || !Number.isFinite(durationSeconds)) {
    return fallback;
  }
  return `${fallback}，用时 ${formatDuration(durationSeconds)}`;
}

function formatDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes === 0) {
    return `${remainingSeconds} 秒`;
  }
  if (remainingSeconds === 0) {
    return `${minutes} 分钟`;
  }
  return `${minutes} 分 ${remainingSeconds} 秒`;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ChatPanel({
  reportId,
  prefillQuestion,
  prefillQaType,
  prefillFile,
  prefillLineStart,
  onPrefillConsumed,
}: {
  reportId: string;
  prefillQuestion: string;
  prefillQaType: QaType;
  prefillFile?: string;
  prefillLineStart?: number;
  onPrefillConsumed: () => void;
}) {
  const [messages, setMessages] = useState<ChatHistoryItem[]>([]);
  const [input, setInput] = useState("");
  const [qaType, setQaType] = useState<QaType>("qa");
  const [isAsking, setIsAsking] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const contextRef = useRef<{ file?: string; line?: number }>({});

  useEffect(() => {
    getQaHistory(reportId).then(setMessages).catch(() => setMessages([]));
    getQaSuggestions(reportId).then(setSuggestions).catch(() => setSuggestions([]));
  }, [reportId]);

  useEffect(() => {
    if (prefillQuestion) {
      setInput(prefillQuestion);
      setQaType(prefillQaType);
      contextRef.current = { file: prefillFile, line: prefillLineStart };
      onPrefillConsumed();
    }
  }, [prefillQuestion, prefillQaType, prefillFile, prefillLineStart, onPrefillConsumed]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  async function handleAsk() {
    if (!input.trim() || isAsking) return;
    const question = input.trim();
    setInput("");
    setIsAsking(true);
    const ctx = contextRef.current;
    contextRef.current = {};
    const userMsg: ChatHistoryItem = {
      message_id: `local-${Date.now()}`,
      role: "user",
      content: question,
      message_type: qaType,
      context_file: ctx.file,
      context_line: ctx.line,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    try {
      const resp = await askQuestion(reportId, {
        question,
        qa_type: qaType,
        context_file: ctx.file,
        context_line_start: ctx.line,
      });
      const assistantMsg: ChatHistoryItem = {
        message_id: resp.message_id,
        role: "assistant",
        content: resp.answer,
        message_type: qaType,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          message_id: `err-${Date.now()}`,
          role: "assistant",
          content: `出错了：${err instanceof Error ? err.message : "未知错误"}`,
          message_type: "qa",
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsAsking(false);
    }
  }

  function handleSuggestionClick(suggestion: string) {
    setInput(suggestion);
    setQaType("qa");
    contextRef.current = {};
  }

  const qaTypeLabels: Record<QaType, string> = { qa: "追问", fix_request: "修代码", test_gen: "写测试" };

  return (
    <article className="chatPanel panel">
      <div className="panelTitle">
        <MessageSquare size={18} />
        追问与交互
      </div>
      <div className="chatMessages" ref={scrollRef}>
        {messages.length === 0 && (
          <p className="muted">对报告有疑问？可以追问 PR 风险、请求修复代码或生成测试用例。</p>
        )}
        {messages.map((msg) => (
          <ChatBubble key={msg.message_id} msg={msg} />
        ))}
        {isAsking && (
          <div className="chatBubble assistant">
            <div className="chatBubbleContent">
              <Loader2 className="spin" size={14} /> 正在思考...
            </div>
          </div>
        )}
      </div>
      {suggestions.length > 0 && messages.length === 0 && (
        <div className="suggestedQuestions">
          {suggestions.map((s) => (
            <button key={s} className="suggestionChip" onClick={() => handleSuggestionClick(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="qaTypeRow">
        {(["qa", "fix_request", "test_gen"] as QaType[]).map((t) => (
          <button
            key={t}
            className={qaType === t ? "qaTypeBtn active" : "qaTypeBtn"}
            onClick={() => setQaType(t)}
            disabled={isAsking}
          >
            {t === "qa" ? <MessageSquare size={14} /> : t === "fix_request" ? <Wrench size={14} /> : <Bug size={14} />}
            {qaTypeLabels[t]}
          </button>
        ))}
      </div>
      <div className="chatInputRow">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          placeholder={
            qaType === "qa" ? "追问 PR 中的问题..." : qaType === "fix_request" ? "描述需要修复的问题..." : "描述需要测试的场景..."
          }
          disabled={isAsking}
        />
        <button onClick={handleAsk} disabled={!input.trim() || isAsking}>
          {isAsking ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
        </button>
      </div>
    </article>
  );
}

function ChatBubble({ msg }: { msg: ChatHistoryItem }) {
  const isUser = msg.role === "user";
  const typeLabel = msg.message_type === "fix_request" ? "[修代码]" : msg.message_type === "test_gen" ? "[写测试]" : "";
  return (
    <div className={`chatBubble ${isUser ? "user" : "assistant"}`}>
      {typeLabel && <span className="chatTypeLabel">{typeLabel}</span>}
      <div className="chatBubbleContent">
        {isUser ? msg.content : <MarkdownText text={msg.content} />}
      </div>
    </div>
  );
}

function MarkdownText({ text }: { text: string }) {
  const html = useMemo(() => renderMarkdown(text), [text]);
  return <div className="markdownText" dangerouslySetInnerHTML={{ __html: html }} />;
}

function renderMarkdown(md: string): string {
  const parts: string[] = [];
  let remaining = md;
  const codePlaceholders: Record<string, string> = {};

  // Extract fenced code blocks first
  let placeholderIdx = 0;
  remaining = remaining.replace(/```(\w*)\n([\s\S]*?)```/g, (_full, lang: string, code: string) => {
    const key = `__CODE_BLOCK_${placeholderIdx++}__`;
    const langAttr = lang ? ` data-lang="${escapeHtml(lang)}"` : "";
    codePlaceholders[key] = `<pre><code${langAttr}>${escapeHtml(code.trimEnd())}</code></pre>`;
    return key;
  });

  // Escape HTML
  remaining = escapeHtml(remaining);

  // Inline code
  remaining = remaining.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Bold
  remaining = remaining.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  // Italic
  remaining = remaining.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  // Links
  remaining = remaining.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');

  // Line breaks
  const lines = remaining.split("\n");
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    // Unordered list items
    if (/^-\s/.test(line)) {
      line = `<li>${line.slice(2)}</li>`;
      if (i === 0 || !/^-\s/.test(lines[i - 1] || "")) {
        line = `<ul>${line}`;
      }
      if (i === lines.length - 1 || !/^-\s/.test(lines[i + 1] || "")) {
        line = `${line}</ul>`;
      }
    } else if (line === "") {
      line = "<br/>";
    }
    parts.push(line);
  }

  remaining = parts.join("\n");

  // Restore code blocks
  for (const [key, html] of Object.entries(codePlaceholders)) {
    remaining = remaining.replace(key, html);
  }

  return remaining;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
