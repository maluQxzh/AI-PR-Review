# AI PR Review Assistant Demo

一个面向 GitHub Pull Request 的 AI 代码评审 demo。用户输入 PR URL 后，系统会拉取 PR 元信息和 diff，生成变更总结、风险文件排行、Review findings、测试建议、PR 描述/标题/labels/walkthrough/changelog 等辅助产物，并提供 GitHub 评论 Markdown 预览。

## 功能

- 输入公开 GitHub PR URL 并创建分析任务。
- 拉取 PR 标题、描述、作者、分支、commits、changed files 和 patch。
- 用规则识别高风险文件：权限、支付、数据库、迁移、安全、配置、错误处理、测试缺失等。
- 可接 OpenAI-compatible LLM 生成结构化 review。
- LLM 不可用时自动降级为规则摘要和启发式 findings。
- 生成可复制的 PR 准备稿：建议标题、类型、labels、描述、walkthrough、changelog、相似 issue/PR 和非阻塞改进建议。
- Web 页面展示报告，并支持加载离线 demo 报告。
- 提供 GitHub Action 示例和 dry-run 评论预览。

## 启动

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

可选环境变量：

```env
GITHUB_TOKEN=
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_FAST=gpt-4.1-mini
LLM_MODEL_STRONG=gpt-4.1
LLM_TIMEOUT_SECONDS=180
LLM_RETRY_TIMEOUT_SECONDS=90
MAX_CONTEXT_FILES=20
MAX_CONTEXT_FILE_CHARS=40000
MAX_RELATED_FILES=12
MAX_HISTORY_ITEMS=10
MAX_GITHUB_PAGES=4
# Optional override. By default the app writes backend/ai_pr_review.db.
# DATABASE_URL=sqlite:///./ai_pr_review.db
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。如果后端或网络不可用，点击 `Load demo` 也能演示完整报告。

## API

- `POST /api/analyze-pr`
- `GET /api/reports/{report_id}`
- `GET /api/reports/{report_id}/result`
- `POST /api/reports/{report_id}/comment`
- `GET /api/demo-report`

`GET /api/reports/{report_id}/result` 会在基础评审结果之外返回可选 `generated_artifacts` 字段。`POST /api/reports/{report_id}/comment` 的 `comment_type` 支持 `summary`、`full` 和 `artifacts`；当前版本只返回预览 Markdown，不会自动写回 GitHub。

## 设计说明

模型选择：

- fast model 用于 PR 摘要、风险粗筛和测试建议。
- strong model 用于 Top N 高风险文件的深度 review。
- 当前实现使用 OpenAI-compatible `/chat/completions`，并通过环境变量切换模型和 base URL。

上下文获取：

- MVP 使用 PR 标题、描述、commits、文件路径、patch、变更规模和测试文件信号。
- 当前增强版会按模式预算补充 changed file 周边代码、函数/类片段、相关测试、README/docs、配置文件、`.ai-review.yml` 和轻量历史 issue/PR 信号。
- 后续可以加入 tree-sitter、embedding 检索调用方和仓库级索引。

误报控制：

- finding 必须有具体文件、行号、证据、影响和修复建议。
- verification pass 会过滤无证据、低置信度、非变更文件、纯风格偏好的建议。
- P2/P3 默认展示在报告中，真实评论到 GitHub 前走 dry-run 预览。

响应速度：

- MVP 使用 FastAPI BackgroundTasks 和 SQLite。
- 标准模式只深度分析 Top 5 高风险文件。
- Deep 模式可扩展到 Top 15，并增加二次校验。
- PR 辅助产物复用已收集的 diff、风险、findings、测试建议和历史 issue/PR 信号；LLM 不可用时使用规则生成，保持离线 demo 可用。
- 后续可用 commit SHA 缓存结果，使用 Celery/RQ + Redis 处理大 PR。

未来扩展：

- GitHub App + Webhook，支持组织级安装。
- PR 评论命令：`/review`、`/summary`、`/ask`。
- 多 Agent：Security、Correctness、Test、Performance、Maintainability。
- 仓库级索引和团队 review 偏好学习。

## 测试

```bash
cd backend
pytest
```

测试覆盖 PR URL 解析、diff 行号提取、风险分类、finding verification 和 PR 辅助产物生成。

## 演示流程

1. 启动后端和前端。
2. 输入公开 GitHub PR URL，或点击 `Load demo`。
3. 查看进度、PR 摘要、高风险文件、具体 findings、测试建议和 PR 准备稿。
4. 复制 GitHub 评论预览，说明 dry-run 后再发评论的安全策略。
