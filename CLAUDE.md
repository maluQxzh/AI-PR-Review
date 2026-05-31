# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在此仓库中工作时提供指引。

## 常用命令

### 后端

```bash
# 安装
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows；Unix 上使用 source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 运行（使用 python -m uvicorn 而非裸 uvicorn，确保使用 venv 中的版本）
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 测试（Windows 上需要设置 PYTHONPATH）
cd backend
$env:PYTHONPATH='.' ; pytest
# 或运行单个测试文件：
$env:PYTHONPATH='.' ; pytest tests/test_verifier.py
```

### 前端

```bash
cd frontend
npm install
npm run dev          # Vite 开发服务器，地址 http://127.0.0.1:5173
npm run build        # TypeScript 检查 + Vite 生产构建
```

### 冒烟检查（前后端一起）

```bash
cd backend ; $env:PYTHONPATH='.' ; pytest ; cd ..\frontend ; npm run build
```

### Git（Windows 沙箱兼容）

```bash
git -c safe.directory=D:/AFile/CodeXProject/AI-PR-Review <命令>
```

## 架构

### 分析流水线

```
POST /api/analyze-pr
  → parse_pr_url (github/parser.py)           # 校验 GitHub PR URL，提取 owner/repo/number
  → GitHubClient.fetch_pull_request            # REST API：PR 信息、文件及 patch、commits（分页获取）
  → classify_files (risk_classifier.py)        # 通过路径关键词 + diff 内容正则，对每个文件评 0-100 分
  → ContextCollector.collect                   # 可选：获取仓库 tree、周围代码、相关测试、
                                               #   仓库文档（.ai-review.yml、README、配置文件）、
                                               #   GitHub issue/PR 历史搜索
  → review_pr (reviewer.py)                    # 调度 LLM，或在不可用时降级为启发式分析
      ├─ OpenAICompatibleProvider.review       # 发送带 JSON schema 的结构化 prompt → ReviewOutput
      │   ├─ Fast 模式：llm_model_fast，0 个审查目标，仅摘要
      │   ├─ Standard 模式：llm_model_strong，审查 Top 5 高风险文件
      │   └─ Deep 模式：llm_model_strong，审查 Top 15 文件 + 二次校验
      ├─ 超时 → 用 fast 模型重试（llm_retry_timeout_seconds）
      └─ 无 API key / API 错误 → 启发式降级
          ├─ 第一阶段：analyze_patterns（pattern_analyzer.py）约 60 条规则 × 6 种语言
          └─ 第二阶段：基于风险原因的模板化 finding（安全兜底）
  → verify_findings (verifier.py)              # 多层流水线：
      1. 剔除文件不在变更集中的 finding
      2. 剔除行号不在新增/修改 hunk 中的 finding
      3. 纯风格问题 → 降级为 P3；非风格问题 → 证据必须与 diff（±5 行内）匹配
      4. 基于上下文的严重级别降级（文档文件、已删除文件、微小变更）
      5. 基于测试覆盖的置信度调整（±5-8%）
      6. 最低置信度截断（0.55）
      7. 精确去重（按 file、line、title），再按三元组 Jaccard 语义去重
  → build_fallback_artifacts + coerce         # PR 元信息、labels、walkthrough、changelog、改进建议
  → build_github_comment                      # 完整 Markdown 报告
```

核心设计：系统**在任何情况下都能生成有用的报告**，即使没有任何凭证 — 启发式降级路径（`reviewer.py` 中的 `_heuristic_review`）和离线演示数据保证了这一点。

### 无凭证 / 降级设计

三种降级层级：
1. **完整 LLM**：`GITHUB_TOKEN` + `LLM_API_KEY` 均已配置 → 完整 AI 审查
2. **仅模式分析**：`GITHUB_TOKEN` 已配置，无 `LLM_API_KEY` → GitHub 数据 + 模式分析器 finding
3. **离线演示**：无任何凭证 → 前端点击"加载演示"，通过后端 `/api/demo-report` 或前端本地 import 加载静态 `demoReport.ts`

### 双模型策略

- **Fast 模型**（`LLM_MODEL_FAST`，默认 `gpt-4.1-mini`）：PR 摘要、风险粗筛、测试建议。当强模型超时时也用于重试。
- **Strong 模型**（`LLM_MODEL_STRONG`，默认 `gpt-4.1`）：高风险文件深度审查、安全/正确性分析、跨文件逻辑判断。在 standard/deep 模式下使用。
- **多模态模型**（`LLM_MODEL_MULTIMODAL`）：当 Q&A 附带图片时使用。

Provider（`OpenAICompatibleProvider`）统一使用 `/chat/completions` 端点，带 `response_format: json_object`。通过 `LLM_BASE_URL` 切换兼容的 API 服务。

### 风险分类器（`risk_classifier.py`）

两种机制：
- **基于路径**：`HIGH_RISK_PATHS` 字典 — 文件名中包含 auth、permission、payment、migration、security、crypto、database、config 等关键词各加 18 分
- **基于内容**：`RISK_PATTERNS` 正则列表 — SQL 模式、访问控制、错误处理、网络请求、TODO 标记、提前返回、并发信号、废弃标记、潜在性能问题
- **维度检测**：`DIMENSION_PATTERNS` 将正则映射到审查维度（security、logic、concurrency、compatibility、performance、maintainability、data），用于定向审查 prompt
- 额外信号：diff 规模（≥120 行：+15）、缺少测试文件（+12）、配置文件后缀（+6）、上下文收集器补充信息

分数封顶 100 分；级别：critical（≥85）、high（≥65）、medium（≥35）、low（<35）。

### 模式分析器（`pattern_analyzer.py`）

数据驱动的静态分析：60+ 个 `PatternRule` 数据类，覆盖 Python、JS/TS、Go、Java、Rust，外加跨语言规则。每条规则包含：正则、语言过滤、严重级别/类别、中文标题/证据/影响/建议/评论模板。每个文件每种规则仅产生一个 finding（已去重）。上限 20 个 finding。在启发式降级模式和 LLM 模式中均会运行。

### 验证流水线（`verifier.py`）

Finding 在进入报告前经过多步后处理：
- 将证据文本与 diff 实际内容交叉验证，通过三元组 Jaccard 相似度匹配
- 通过关键词集合检测纯风格问题（`_STYLE_KEYWORDS` vs `_RISK_EXCLUSIONS`）
- 根据对应测试文件是否被修改来调整置信度
- `_build_source_test_map` 使用命名约定启发式（Python、Jest、Go、Rust 模式）猜测测试文件与源文件的对应关系
- 此步骤必不可少，因为 LLM 可能在 diff 中不存在的文件/行上报告问题

### 上下文收集器（`context_collector.py`）

为每个目标文件补充：
- 每个新增 hunk 周围 ±8 行代码
- 最近的函数/类符号上下文
- 相关测试文件（基于命名启发式）
- 仓库文档（README、.ai-review.yml、配置文件）
- 历史搜索（按标题和文件路径关键词搜索 GitHub issue/PR）
- 全部由设置中的 `MAX_CONTEXT_FILES`、`MAX_CONTEXT_FILE_CHARS` 等限制

### 数据库

通过 SQLAlchemy 使用 SQLite，带轻量级列迁移（`db/session.py` 中的 `_ensure_lightweight_columns`）。检查 `PRAGMA table_info` 并通过 `ALTER TABLE ADD COLUMN` 添加新字段 — 与现有数据库兼容。表：`reports`、`changed_files`、`findings`、`chat_messages`、`review_feedback`。

### 前端架构

单文件 React 19 应用（`main.tsx`），使用 Vite 构建，无路由 — 所有 UI 状态通过 `useState` 管理。主要区域：URL 输入 + 模式选择器、带 SSE 及轮询降级的进度条、报告网格（摘要、上下文覆盖、PR 准备、风险文件、findings、测试建议、改进建议、GitHub 评论预览、Q&A 对话面板）。Q&A 支持三种模式：追问、修代码、写测试 — 每种模式有定制的系统 prompt，并保留对话历史。

### API 一览

| 方法 | 路径 | 用途 |
|--------|------|---------|
| POST | `/api/analyze-pr` | 创建异步分析任务 |
| GET | `/api/reports` | 列出最近报告 |
| GET | `/api/reports/{id}` | 查询状态 |
| GET | `/api/reports/{id}/events` | SSE 状态推送（降级为轮询） |
| GET | `/api/reports/{id}/result` | 获取完整报告 |
| POST | `/api/reports/{id}/retry` | 重新分析 |
| POST | `/api/reports/{id}/cancel` | 取消分析 |
| POST | `/api/reports/{id}/comment` | dry-run GitHub 评论预览 |
| POST | `/api/reports/{id}/qa` | 交互式问答 |
| GET | `/api/reports/{id}/qa/history` | 对话历史 |
| GET | `/api/reports/{id}/qa/suggestions` | 自动生成的追问建议 |
| GET | `/api/demo-report` | 离线演示数据 |

### 配置

设置由 `pydantic-settings` 从 `.env` 文件加载。所有配置项见 `backend/app/config.py:Settings`。关键环境变量：`GITHUB_TOKEN`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL_FAST`、`LLM_MODEL_STRONG`、`LLM_MODEL_MULTIMODAL`、`DATABASE_URL`（默认为 `backend/ai_pr_review.db`），以及各种 `MAX_*` 限制。

## 关键实现规则（来自 AGENTS.md）

- 即使没有 GitHub 或 LLM 凭证，演示也必须可运行 — 此为硬性要求。
- 不要提交 `.env`、虚拟环境、SQLite 数据库、`node_modules` 或构建产物。
- 修改后端行为时，在 `backend/tests/` 下添加或更新测试。
- 修改 API/报告 schema 时，必须同时更新：后端 Pydantic 模型、前端 TypeScript 类型、离线演示数据。
- 保留离线演示路径 — 这对演示很重要。
- Review finding 必须有证据支撑：文件、行号、影响、置信度、建议必须齐全。
- 除非明确要求，否则保持 README.md 中的公开 API 形态不变。
- 优先采用小而聚焦的修改，而非大范围重写。
