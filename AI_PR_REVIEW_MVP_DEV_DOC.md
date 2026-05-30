# AI PR Review 助手 MVP 开发文档

## 1. 项目概述

本项目面向 GitHub Pull Request 场景，开发一个以 AI 辅助分析为核心的代码评审工具。用户输入 GitHub PR 地址后，系统自动获取 PR 元信息、代码变更和必要上下文，生成 PR 变更总结、风险文件识别、Review 建议和测试建议，帮助开发者提高 Review 效率与质量。

MVP 阶段优先实现“可运行、可演示、可扩展”的核心闭环：

```text
输入 GitHub PR URL
  -> 拉取 PR 元信息和 diff
  -> 解析变更文件
  -> AI 生成摘要和风险判断
  -> AI 深度审查高风险文件
  -> 输出可视化报告
  -> 可选模拟/真实评论到 PR
```

## 2. MVP 目标

### 2.1 核心能力

- 支持用户输入 GitHub PR URL。
- 自动获取 PR 标题、描述、作者、分支、提交、变更文件和 diff。
- 自动生成 PR 变更总结。
- 对变更文件进行风险分级。
- 识别潜在问题，包括逻辑错误、边界条件、权限风险、安全风险、兼容性风险、测试缺失等。
- 生成 Review 建议，包括问题描述、严重级别、证据代码、修复建议和置信度。
- 生成测试建议。
- 在 Web 页面展示报告。
- 支持 GitHub Action 触发分析，并将摘要或评论草稿写回 PR。

### 2.2 非 MVP 范围

以下能力暂不作为第一版强制目标：

- 私有仓库组织级 GitHub App 安装。
- 对整个代码库建立长期索引。
- 多平台 Git 托管支持，例如 GitLab、Bitbucket。
- 自动提交修复代码。
- 完整的团队权限管理和计费系统。
- 大规模并发任务调度。

## 3. 推荐技术栈

### 3.1 后端与分析引擎

- 语言：Python 3.11+
- Web 框架：FastAPI
- HTTP 客户端：httpx
- GitHub API：GitHub REST API
- 数据校验：Pydantic
- ORM：SQLAlchemy
- 数据库：
  - MVP：SQLite
  - 进阶：PostgreSQL
- 后台任务：
  - MVP：FastAPI BackgroundTasks 或同步任务
  - 进阶：Celery/RQ + Redis
- 代码结构解析：tree-sitter
- LLM Provider 抽象：
  - OpenAI
  - Anthropic
  - Gemini
  - OpenAI-compatible provider

### 3.2 前端

- React
- TypeScript
- Vite
- UI 组件库：可选 shadcn/ui、Ant Design 或自定义轻量组件
- 代码高亮：shiki 或 highlight.js
- 状态管理：React Query + 本地 state

### 3.3 GitHub 集成

- MVP：
  - 用户提供 GitHub Token 或服务端配置 Token。
  - 输入公开仓库 PR URL 后分析。
  - 提供 GitHub Action 模板。
- 进阶：
  - GitHub App + Webhook。
  - 支持 `/review`、`/ask` 等 PR 评论命令。

## 4. 系统架构

```text
┌──────────────────────────┐
│        Web Frontend       │
│ React + TypeScript        │
│ PR 输入 / 报告展示        │
└─────────────┬────────────┘
              │ HTTP API
┌─────────────▼────────────┐
│        FastAPI Backend    │
│ 任务管理 / 报告查询       │
└─────────────┬────────────┘
              │
┌─────────────▼────────────┐
│      PR Analysis Engine   │
│ diff 解析 / 风险分类      │
│ 上下文补充 / AI Review    │
└─────────────┬────────────┘
              │
      ┌───────┴────────┐
      │                │
┌─────▼─────┐    ┌─────▼─────┐
│ GitHub API│    │ LLM API   │
│ PR/diff   │    │ Review    │
└───────────┘    └───────────┘
              │
┌─────────────▼────────────┐
│       SQLite/PostgreSQL   │
│ report / finding / files  │
└──────────────────────────┘
```

## 5. 核心模块设计

### 5.1 GitHub PR Fetcher

职责：

- 解析 PR URL。
- 获取 PR 基础信息。
- 获取变更文件列表。
- 获取每个文件的 patch。
- 获取 PR commits。
- 可选获取 issue/ticket 上下文。

输入：

```json
{
  "pr_url": "https://github.com/owner/repo/pull/123"
}
```

输出：

```json
{
  "owner": "owner",
  "repo": "repo",
  "number": 123,
  "title": "Fix permission check",
  "description": "...",
  "base_branch": "main",
  "head_branch": "feature/permission-fix",
  "files": [
    {
      "filename": "src/auth/check.ts",
      "status": "modified",
      "additions": 30,
      "deletions": 8,
      "patch": "@@ ..."
    }
  ]
}
```

### 5.2 Diff Parser

职责：

- 解析 unified diff。
- 提取新增行、删除行和上下文行。
- 标记变更函数或类。
- 过滤低价值文件，例如 lock file、构建产物、图片、二进制文件。
- 对大 patch 做压缩。

过滤建议：

- 默认跳过：
  - `package-lock.json`
  - `pnpm-lock.yaml`
  - `yarn.lock`
  - `dist/**`
  - `build/**`
  - `*.min.js`
  - 图片、字体、二进制文件
- 但如果 PR 只修改 lock file，需要保留依赖变化摘要。

### 5.3 Context Retriever

职责：

- 根据 diff 位置补充相关上下文。
- 获取变更代码所在函数或类。
- 获取相邻测试文件。
- 获取相关配置文件。
- 获取 README 或项目说明中的关键约束。

MVP 可以采用轻量策略：

```text
每个变更文件：
  - patch 本身
  - 文件路径和语言
  - PR 标题和描述
  - 同目录测试文件名称
  - package / requirements / pyproject 等依赖配置摘要
```

进阶策略：

- 使用 tree-sitter 提取变更函数。
- 使用 embedding 检索相关调用方。
- 建立仓库级索引。
- 读取团队 review 规则文件，例如 `.ai-review.yml`。

### 5.4 Risk Classifier

职责：

- 对每个变更文件进行风险评分。
- 决定哪些文件进入深度 Review。
- 降低全量调用强模型的成本。

风险评分维度：

| 维度 | 示例 |
|---|---|
| 文件类型 | auth、payment、database、migration、security、config 风险更高 |
| 变更规模 | 大量新增/删除代码风险更高 |
| 代码行为 | 权限判断、SQL、网络请求、并发、缓存、错误处理风险更高 |
| 测试情况 | 无测试或测试删除风险更高 |
| 依赖变化 | 新增依赖、升级主版本风险更高 |

输出示例：

```json
{
  "filename": "src/auth/check.ts",
  "risk_level": "high",
  "risk_score": 82,
  "reasons": [
    "修改权限校验逻辑",
    "缺少对应测试变更",
    "新增 early return 可能绕过后续检查"
  ]
}
```

### 5.5 LLM Reviewer

职责：

- 生成 PR 总结。
- 对高风险文件进行深度审查。
- 输出结构化 findings。
- 生成测试建议。

推荐分层：

```text
Fast model:
  - PR 摘要
  - 文件风险粗筛
  - 变更分类

Strong model:
  - 高风险文件深度 Review
  - 安全/权限/数据一致性分析
  - 跨文件逻辑判断

Verification pass:
  - 去重
  - 过滤泛泛建议
  - 校验 finding 是否有证据
  - 生成置信度
```

Finding 输出结构：

```json
{
  "title": "权限校验可能被绕过",
  "severity": "P1",
  "confidence": 0.82,
  "file": "src/auth/check.ts",
  "line": 42,
  "category": "security",
  "evidence": "新增的 early return 在 role 为空时直接返回 true。",
  "impact": "未授权用户可能通过特定请求访问受保护资源。",
  "suggestion": "将 early return 改为拒绝访问，并为 role 为空的情况补充单元测试。",
  "comment_draft": "这里的 early return 可能绕过后续权限校验..."
}
```

### 5.6 Report Generator

职责：

- 聚合 PR 摘要、风险文件、findings 和测试建议。
- 生成 Web 报告数据。
- 生成 GitHub 评论 Markdown。

报告结构：

```json
{
  "report_id": "uuid",
  "status": "completed",
  "summary": {
    "what_changed": "...",
    "risk_overview": "...",
    "review_focus": ["权限", "测试覆盖", "错误处理"]
  },
  "file_risks": [],
  "findings": [],
  "test_suggestions": [],
  "github_comment_markdown": "..."
}
```

## 6. API 设计

### 6.1 创建分析任务

`POST /api/analyze-pr`

请求：

```json
{
  "pr_url": "https://github.com/owner/repo/pull/123",
  "mode": "standard",
  "post_comment": false
}
```

响应：

```json
{
  "report_id": "uuid",
  "status": "queued"
}
```

### 6.2 查询报告状态

`GET /api/reports/{report_id}`

响应：

```json
{
  "report_id": "uuid",
  "status": "running",
  "progress": 60,
  "current_step": "Reviewing high-risk files"
}
```

### 6.3 获取完整报告

`GET /api/reports/{report_id}/result`

响应：

```json
{
  "report_id": "uuid",
  "status": "completed",
  "pr": {},
  "summary": {},
  "file_risks": [],
  "findings": [],
  "test_suggestions": []
}
```

### 6.4 发布 GitHub 评论

`POST /api/reports/{report_id}/comment`

请求：

```json
{
  "comment_type": "summary",
  "dry_run": true
}
```

响应：

```json
{
  "posted": false,
  "dry_run": true,
  "markdown": "..."
}
```

### 6.5 GitHub Action 入口

`POST /api/github-action/analyze`

请求：

```json
{
  "repository": "owner/repo",
  "pull_number": 123,
  "commit_sha": "...",
  "callback_mode": "comment"
}
```

## 7. 数据库模型

### 7.1 reports

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 报告 ID |
| pr_url | text | PR 地址 |
| owner | text | 仓库 owner |
| repo | text | 仓库名 |
| pull_number | integer | PR 编号 |
| title | text | PR 标题 |
| status | text | queued/running/completed/failed |
| progress | integer | 0-100 |
| summary | json | PR 摘要 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### 7.2 changed_files

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 文件记录 ID |
| report_id | uuid | 报告 ID |
| filename | text | 文件路径 |
| status | text | added/modified/removed |
| additions | integer | 新增行 |
| deletions | integer | 删除行 |
| patch | text | diff patch |
| risk_level | text | low/medium/high/critical |
| risk_score | integer | 0-100 |
| risk_reasons | json | 风险原因 |

### 7.3 findings

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | Finding ID |
| report_id | uuid | 报告 ID |
| file | text | 文件路径 |
| line | integer | 行号 |
| title | text | 问题标题 |
| severity | text | P0/P1/P2/P3 |
| category | text | security/logic/test/performance/maintainability |
| confidence | float | 0-1 |
| evidence | text | 证据 |
| impact | text | 影响 |
| suggestion | text | 修复建议 |
| comment_draft | text | 评论草稿 |

### 7.4 review_feedback

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 反馈 ID |
| finding_id | uuid | Finding ID |
| user_action | text | accepted/rejected/false_positive |
| note | text | 用户备注 |
| created_at | datetime | 创建时间 |

## 8. 前端页面设计

### 8.1 首页 / 分析入口

功能：

- 输入 GitHub PR URL。
- 选择分析模式：
  - Fast：快速摘要和风险扫描。
  - Standard：摘要 + 风险文件深度 Review。
  - Deep：更多上下文和二次校验。
- 选择是否 dry-run GitHub 评论。
- 展示分析进度。

### 8.2 报告页

主要区域：

- PR 基础信息。
- PR 变更总结。
- 风险概览。
- 高风险文件排行。
- Findings 列表。
- 测试建议。
- GitHub 评论预览。

Finding 卡片字段：

- 严重级别。
- 置信度。
- 文件和行号。
- 问题说明。
- 影响范围。
- 修复建议。
- 按钮：
  - 复制评论。
  - 标记误报。
  - 标记已采纳。

### 8.3 文件风险页

功能：

- 按风险排序展示文件。
- 展示每个文件的变更规模和风险原因。
- 支持点击查看 patch。

## 9. GitHub Action 设计

项目可以提供一个示例 workflow：

```yaml
name: AI PR Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  ai_review:
    runs-on: ubuntu-latest
    steps:
      - name: Run AI PR Review
        uses: your-org/ai-pr-review-action@v1
        with:
          pr_url: ${{ github.event.pull_request.html_url }}
          mode: standard
          post_comment: true
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          AI_REVIEW_API_URL: ${{ secrets.AI_REVIEW_API_URL }}
          AI_REVIEW_API_KEY: ${{ secrets.AI_REVIEW_API_KEY }}
```

Action 的职责：

- 读取 PR URL。
- 调用后端 `/api/github-action/analyze`。
- 轮询结果或等待同步响应。
- 将 summary 或 finding 评论到 PR。

## 10. Prompt 设计原则

### 10.1 总体原则

- 要求模型只输出有证据的问题。
- 每条建议必须包含文件、行号、影响和修复建议。
- 区分“确定问题”和“需要确认的问题”。
- 限制泛泛风格建议。
- 控制 findings 数量，优先输出高风险问题。

### 10.2 Review Prompt 输出格式

要求模型输出 JSON：

```json
{
  "findings": [
    {
      "title": "...",
      "severity": "P1",
      "confidence": 0.8,
      "category": "security",
      "file": "...",
      "line": 10,
      "evidence": "...",
      "impact": "...",
      "suggestion": "...",
      "comment_draft": "..."
    }
  ],
  "test_suggestions": [
    {
      "title": "...",
      "reason": "...",
      "suggested_case": "..."
    }
  ]
}
```

### 10.3 二次校验 Prompt

目标：

- 删除没有明确证据的 finding。
- 合并重复 finding。
- 降低泛泛建议的优先级。
- 标记低置信度问题。

校验规则：

```text
保留 finding 的条件：
  - 能指向具体文件和变更行
  - 能解释实际影响
  - 建议与 diff 直接相关
  - 不是单纯代码风格偏好
```

## 11. 误报与漏报控制

### 11.1 降低误报

- 输出前使用 verification pass。
- findings 必须引用具体文件和行号。
- 限制低置信度建议直接评论到 PR。
- 对 P2/P3 建议默认放入报告，不自动 inline 评论。
- 支持用户标记 false positive，用于后续优化 prompt 或规则。

### 11.2 降低漏报

- 对高风险路径做规则加权：
  - `auth`
  - `permission`
  - `payment`
  - `migration`
  - `security`
  - `crypto`
  - `database`
- 针对关键类别使用专项检查：
  - 权限绕过
  - SQL 注入
  - XSS
  - 空指针/None
  - 并发竞争
  - 数据迁移兼容性
  - 错误处理缺失
  - 测试缺失

## 12. 响应速度设计

MVP 策略：

- 小 PR 同步分析。
- 大 PR 进入后台任务。
- 先返回摘要和风险分类，再逐步生成深度 findings。
- 默认只深度分析 Top N 高风险文件。
- 缓存同一个 commit SHA 的分析结果。

推荐模式：

| 模式 | 说明 |
|---|---|
| Fast | 只做摘要、文件风险和测试建议 |
| Standard | 分析 Top 5 高风险文件 |
| Deep | 分析 Top 15 高风险文件，并做二次校验 |

## 13. 项目目录建议

```text
ai-pr-review/
  backend/
    app/
      main.py
      api/
        routes_analyze.py
        routes_reports.py
        routes_github.py
      core/
        config.py
        logging.py
      github/
        client.py
        parser.py
      analyzer/
        diff_parser.py
        context_retriever.py
        risk_classifier.py
        reviewer.py
        verifier.py
        report_generator.py
      llm/
        base.py
        openai_provider.py
        anthropic_provider.py
      models/
        report.py
        finding.py
        changed_file.py
      db/
        session.py
        migrations/
      tests/
  frontend/
    src/
      pages/
        AnalyzePage.tsx
        ReportPage.tsx
      components/
        PrInput.tsx
        ProgressPanel.tsx
        SummaryPanel.tsx
        FileRiskTable.tsx
        FindingCard.tsx
        CodeDiffViewer.tsx
      api/
        client.ts
      types/
        report.ts
  action/
    action.yml
    src/
      index.ts
  docker-compose.yml
  README.md
```

## 14. 开发里程碑

### Milestone 1：基础 PR 分析闭环

- 创建 FastAPI 项目。
- 实现 PR URL 解析。
- 调用 GitHub API 获取 PR 和 changed files。
- 保存 report 和 changed_files。
- 实现简单 PR summary。
- 前端输入 PR URL 并展示结果。

验收标准：

- 输入公开 PR URL 后能展示 PR 标题、描述、文件列表和摘要。

### Milestone 2：风险分类与 Review 建议

- 实现 diff parser。
- 实现规则型 risk classifier。
- 调用 LLM 对高风险文件生成 findings。
- 前端展示风险文件和 findings。

验收标准：

- 系统能输出至少 3 类问题建议，并带文件、行号和严重级别。

### Milestone 3：误报控制与报告体验

- 实现 verification pass。
- 实现 finding 去重。
- 实现测试建议生成。
- 实现 GitHub 评论 Markdown 预览。
- 前端支持标记误报/采纳。

验收标准：

- 报告结构清晰，低价值建议明显减少。

### Milestone 4：GitHub Action 集成

- 创建 Action。
- Action 调用后端 API。
- 支持将摘要评论到 PR。
- 支持 dry-run。

验收标准：

- PR 创建或更新后，GitHub Action 可以自动生成 AI Review 评论。

### Milestone 5：展示与扩展设计

- 增加项目规则配置 `.ai-review.yml`。
- 增加模型 provider 配置。
- 编写 README 和演示说明。
- 准备示例 PR 和截图。

验收标准：

- 项目可以完整演示，且文档说明未来可扩展到 GitHub App、多模型、多 Agent 和仓库索引。

## 15. 配置文件设计

仓库级 `.ai-review.yml` 示例：

```yaml
review:
  mode: standard
  max_findings: 8
  min_confidence_to_comment: 0.75
  focus:
    - security
    - correctness
    - tests
  ignore_paths:
    - "dist/**"
    - "build/**"
    - "*.lock"
  high_risk_paths:
    - "src/auth/**"
    - "src/payment/**"
    - "migrations/**"

model:
  fast: "gpt-4.1-mini"
  strong: "gpt-4.1"
  fallback: "gpt-4.1-mini"
```

## 16. 安全与权限

- GitHub Token 只请求必要权限。
- MVP 对公开仓库可使用低权限 token。
- 后端不要在日志里打印 token、完整 Authorization header 或用户隐私信息。
- 对 PR URL 做严格校验，避免 SSRF。
- 限制单次分析文件数量和 patch 大小。
- 对外部 API 调用设置超时。
- 对 LLM 输出做 JSON schema 校验。
- 评论到 GitHub 前默认提供 dry-run。

## 17. 可扩展方向

### 17.1 GitHub App

后续可以从 GitHub Action 升级为 GitHub App：

- 支持组织级安装。
- 自动监听 PR opened/synchronize。
- 支持 PR 评论命令 `/review`、`/ask`、`/summary`。
- 支持统一配置和后台任务队列。

### 17.2 多 Agent Review

将 Review 拆成多个专门 Agent：

- Security Reviewer
- Correctness Reviewer
- Test Reviewer
- Performance Reviewer
- Maintainability Reviewer

最后由 Aggregator 合并、去重、排序。

### 17.3 仓库级上下文索引

- 建立代码 embedding 索引。
- 检索相关调用方和被调用方。
- 结合 README、架构文档、历史 issue。
- 支持“这个 PR 是否符合需求”的深度判断。

### 17.4 团队规则学习

- 记录用户采纳和误报反馈。
- 沉淀团队 review 偏好。
- 自动更新 prompt 或规则配置。

## 18. Demo 建议

演示时建议准备一个包含真实风险的示例 PR，例如：

- 修改权限判断但缺少测试。
- 新增数据库查询但没有处理空值。
- 改动 API 返回结构但没有更新调用方。
- 删除错误处理逻辑。

演示流程：

```text
1. 输入 PR URL
2. 系统显示分析进度
3. 展示 PR 总结
4. 展示高风险文件
5. 展示具体 Review finding
6. 展示测试建议
7. 展示 GitHub 评论预览
8. 说明 GitHub Action 自动化接入
```

## 19. 最小可交付清单

- 后端 FastAPI 服务。
- 前端 React 报告页面。
- GitHub PR 获取模块。
- Diff 解析模块。
- 风险分类模块。
- LLM Review 模块。
- 报告生成模块。
- SQLite 数据存储。
- GitHub Action 示例。
- README 使用说明。
- 示例 PR 分析报告。

## 20. 推荐开发顺序

1. 后端 PR URL 解析和 GitHub API 拉取。
2. 数据模型和报告存储。
3. 简单 PR summary。
4. 前端输入和报告展示。
5. diff parser 和文件风险分类。
6. LLM 深度 Review。
7. verification pass。
8. GitHub 评论预览。
9. GitHub Action。
10. 文档、演示数据和部署脚本。

