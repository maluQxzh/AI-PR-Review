import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  FileCode2,
  GitPullRequest,
  Loader2,
  Play,
  ShieldAlert,
  TestTube2,
} from "lucide-react";
import { analyzePr, getDemoReport, getReport, getStatus } from "./api/client";
import type { FileRisk, Finding, Mode, ReportResult } from "./types/report";
import "./styles.css";

const modeLabels: Record<Mode, string> = {
  fast: "快速",
  standard: "标准",
  deep: "深度",
};

const stepLabels: Record<string, string> = {
  Queued: "已排队",
  "Parsing pull request URL": "正在解析 Pull Request 地址",
  "Fetching GitHub pull request": "正在获取 GitHub Pull Request",
  "Classifying changed files": "正在评估变更文件风险",
  "Generating AI review": "正在生成 AI Review",
  Completed: "已完成",
  Failed: "失败",
};

const riskLevelLabels: Record<string, string> = {
  critical: "严重",
  high: "高",
  medium: "中",
  low: "低",
};

function translateStep(step: string) {
  return stepLabels[step] ?? step;
}

function App() {
  const [prUrl, setPrUrl] = useState("");
  const [mode, setMode] = useState<Mode>("standard");
  const [status, setStatus] = useState("准备就绪");
  const [progress, setProgress] = useState(0);
  const [report, setReport] = useState<ReportResult | null>(null);
  const [error, setError] = useState("");

  async function runAnalysis() {
    setError("");
    setReport(null);
    setStatus("正在创建分析任务");
    setProgress(5);
    try {
      const task = await analyzePr(prUrl, mode);
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const next = await getStatus(task.report_id);
        setStatus(translateStep(next.current_step));
        setProgress(next.progress);
        if (next.status === "completed") {
          setReport(await getReport(task.report_id));
          return;
        }
        if (next.status === "failed") {
          throw new Error(next.error ?? "分析失败");
        }
        await new Promise((resolve) => setTimeout(resolve, 900));
      }
      throw new Error("等待分析结果超时。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "未知错误");
      setStatus("失败");
      setProgress(100);
    }
  }

  async function loadDemo() {
    setError("");
    setStatus("已加载离线演示报告");
    setProgress(100);
    setReport(await getDemoReport());
  }

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <div className="eyebrow">
            <GitPullRequest size={16} />
            AI PR 评审助手
          </div>
          <h1>Pull Request 风险扫描与评审草稿</h1>
        </div>
        <button className="ghostButton" onClick={loadDemo}>
          <FileCode2 size={18} />
          加载演示
        </button>
      </section>

      <section className="workbench">
        <div className="inputPanel">
          <label htmlFor="pr-url">GitHub PR URL</label>
          <div className="urlRow">
            <input
              id="pr-url"
              value={prUrl}
              onChange={(event) => setPrUrl(event.target.value)}
              placeholder="https://github.com/owner/repo/pull/123"
            />
            <button onClick={runAnalysis} disabled={!prUrl.trim()}>
              <Play size={18} />
              开始分析
            </button>
          </div>
          <div className="modeRow" aria-label="分析模式">
            {(["fast", "standard", "deep"] as Mode[]).map((item) => (
              <button
                key={item}
                className={mode === item ? "mode active" : "mode"}
                onClick={() => setMode(item)}
              >
                {modeLabels[item]}
              </button>
            ))}
          </div>
          <div className="progressBlock">
            <div className="statusText">
              {progress > 0 && progress < 100 ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
              {status}
            </div>
            <div className="progressTrack">
              <div style={{ width: `${progress}%` }} />
            </div>
          </div>
          {error && <div className="errorBox">{error}</div>}
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
      <p>输入公开的 GitHub PR 地址，或加载离线演示报告查看完整流程。</p>
    </section>
  );
}

function ReportView({ report }: { report: ReportResult }) {
  const highRiskCount = report.file_risks.filter((file) => ["critical", "high"].includes(file.risk_level)).length;
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
        <div className="fileList">
          {report.file_risks.map((file) => (
            <FileRiskRow key={file.filename} file={file} />
          ))}
        </div>
      </article>

      <article className="panel findingsPanel">
        <div className="panelTitle">
          <ShieldAlert size={18} />
          评审问题
        </div>
        <div className="findingList">
          {report.findings.map((finding) => (
            <FindingCard key={`${finding.file}:${finding.line}:${finding.title}`} finding={finding} />
          ))}
          {report.findings.length === 0 && <p className="muted">校验后没有发现有证据支撑的问题。</p>}
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function FileRiskRow({ file }: { file: FileRisk }) {
  return (
    <details className={`fileRisk ${file.risk_level}`}>
      <summary>
        <span>{file.filename}</span>
        <b title={`风险等级：${riskLevelLabels[file.risk_level] ?? file.risk_level}`}>{file.risk_score}</b>
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

function FindingCard({ finding }: { finding: Finding }) {
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
      <button className="copyButton" onClick={() => navigator.clipboard.writeText(finding.comment_draft)}>
        <Clipboard size={16} />
        复制评论
      </button>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
