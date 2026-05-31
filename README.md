# AI PR Review Assistant Demo

一个面向 GitHub Pull Request 的 AI 代码评审 demo。用户输入公开 PR URL 后，系统会拉取 PR 元信息、changed files 和 diff，生成风险概览、文件风险排行、结构化 review findings、测试建议、PR 准备产物，并提供可复制的 GitHub 评论 Markdown 预览。

项目同时保留离线演示数据：即使没有 GitHub token 或 LLM key，也可以展示完整 UI 流程。

## 功能

- 输入公开 GitHub PR URL，异步创建分析任务并通过 SSE 展示进度。
- 支持快速、标准、深度三种分析模式，可取消任务、失败重试、查看历史报告。
- 拉取 PR 标题、描述、作者、分支、commits、changed files 和 patch。
- 通过规则识别高风险文件：认证/授权、支付、数据库、迁移、安全、配置、错误处理、并发、性能、测试缺失等。
- 为大 PR 使用 diff budgeter：优先保留高风险文件完整 patch，压缩中等风险 patch，对低价值或超预算文件只保留摘要上下文。
- 可接 OpenAI-compatible `/chat/completions` 生成结构化中文评审；未配置或调用失败时自动降级到规则分析和启发式 findings。
- 生成 PR 准备产物：建议标题、类型、labels、PR 描述、walkthrough、changelog、相似 issue/PR、非阻塞改进建议和文档建议。
- 提供报告追问能力：可针对整体报告、单个 finding、单个文件追问，也可请求修复代码或测试用例。
- 前端展示摘要、上下文覆盖、风险文件、findings、测试建议、PR 准备稿、改进建议、相似历史项和 GitHub 评论预览。

## 项目结构

```text
backend/
  app/
    main.py                  # FastAPI app entrypoint 和 CORS
    api/                     # analyze/report/demo/qa 路由
    analyzer/                # 风险分类、diff budget、上下文收集、review、验证、产物生成
    db/                      # SQLite/SQLAlchemy 模型和轻量迁移
    github/                  # PR URL 解析和 GitHub REST client
    llm/                     # OpenAI-compatible provider
    models/                  # Pydantic schemas
  tests/                     # 后端测试
frontend/
  src/
    main.tsx                 # React UI
    api/                     # API client
    data/                    # 离线 demo report
    types/                   # TypeScript report types
action/
  action.yml                 # Composite GitHub Action 示例
.github/workflows/
  ai-pr-review.yml           # 示例 workflow
```

## 启动

### Backend

推荐在仓库根目录执行：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

使用 `python -m uvicorn` 可以确保走当前虚拟环境。若 Windows 上遇到端口绑定问题，可换成其他端口。

### Frontend

```powershell
cd frontend
npm install
$env:VITE_API_BASE_URL='http://127.0.0.1:8765'
npm run dev
```

打开 `http://127.0.0.1:5173`。如果后端、GitHub 或 LLM 暂不可用，可以点击“加载演示”查看离线报告。

## 环境变量

后端从仓库根目录 `.env` 和 `backend/.env` 读取配置，常用项如下：

```env
GITHUB_TOKEN=
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_FAST=gpt-4.1-mini
LLM_MODEL_STRONG=gpt-4.1
LLM_MODEL_MULTIMODAL=gpt-4.1
LLM_TIMEOUT_SECONDS=180
LLM_RETRY_TIMEOUT_SECONDS=90
LLM_QA_TEMPERATURE=0.3
LLM_MAX_CONTEXT_MESSAGES=20
MAX_FILES=80
MAX_PATCH_CHARS=14000
MAX_CONTEXT_FILES=20
MAX_CONTEXT_FILE_CHARS=40000
MAX_RELATED_FILES=12
MAX_HISTORY_ITEMS=10
MAX_GITHUB_PAGES=4
ALLOW_LOCALHOST_DEV_ORIGINS=true
# DATABASE_URL=sqlite:///./ai_pr_review.db
```

说明：

- `GITHUB_TOKEN`：可选的 GitHub Personal Access Token，提高 API 限额（匿名访问极易触发 403），并支持私有仓库访问。
- `LLM_API_KEY`：LLM 服务的 API Key。未配置时系统仍会返回规则分析和离线 demo，不会报错。
- `LLM_BASE_URL`：OpenAI-compatible 的 `/chat/completions` 端点地址，可切换到其他兼容服务。
- `LLM_MODEL_FAST`：Fast 模式下使用的模型，负责 PR 摘要、风险粗筛、测试建议；强模型超时时也会用此模型重试。
- `LLM_MODEL_STRONG`：Standard / Deep 模式下使用的模型，负责高风险文件深度审查、安全/正确性分析、跨文件逻辑判断。
- `LLM_MODEL_MULTIMODAL`：当 Q&A 附带图片时使用的多模态模型。
- `LLM_TIMEOUT_SECONDS`：单次 LLM 调用的超时秒数，超时后将使用 fast 模型重试。
- `LLM_RETRY_TIMEOUT_SECONDS`：超时重试时 fast 模型的超时秒数。
- `LLM_QA_TEMPERATURE`：Q&A 对话中 LLM 的 temperature 参数，控制回复随机性。
- `LLM_MAX_CONTEXT_MESSAGES`：Q&A 对话保留的最大历史消息数。
- `MAX_FILES`：单次分析最多拉取的 PR 变更文件数。
- `MAX_PATCH_CHARS`：所有文件 patch 合计的最大字符数，超出后由 diff budgeter 按优先级裁剪。
- `MAX_CONTEXT_FILES`：上下文收集器最多补充的周边文件数（README、配置、测试等）。
- `MAX_CONTEXT_FILE_CHARS`：上下文收集器补充内容的合计最大字符数。
- `MAX_RELATED_FILES`：最多查找的相关测试/配置文件数。
- `MAX_HISTORY_ITEMS`：GitHub issue/PR 历史搜索最多返回的条目数。
- `MAX_GITHUB_PAGES`：GitHub API 分页获取的最大页数。
- `ALLOW_LOCALHOST_DEV_ORIGINS`：是否允许 localhost 来源的 CORS 请求，本地开发时建议开启。
- `DATABASE_URL`：SQLite 数据库路径，默认为 `backend/ai_pr_review.db`。轻量迁移逻辑在启动时自动补齐新增列。

前端默认 API 地址是 `http://127.0.0.1:8000`，本地推荐用：

```env
VITE_API_BASE_URL=http://127.0.0.1:8765
```

## API

- `POST /api/analyze-pr`：创建异步分析任务。
- `GET /api/reports`：列出最近报告。
- `GET /api/reports/{report_id}`：获取报告状态。
- `GET /api/reports/{report_id}/events`：SSE 进度流。
- `GET /api/reports/{report_id}/result`：获取完整报告结果。
- `POST /api/reports/{report_id}/retry`：基于原 PR URL 和模式创建重试任务。
- `POST /api/reports/{report_id}/cancel`：请求取消运行中的任务。
- `POST /api/reports/{report_id}/comment`：返回 dry-run 评论 Markdown；`comment_type` 支持 `summary`、`full`、`artifacts`。
- `POST /api/reports/{report_id}/qa`：基于报告上下文追问，`qa_type` 支持 `qa`、`fix_request`、`test_gen`。
- `GET /api/reports/{report_id}/qa/history`：获取追问历史。
- `GET /api/reports/{report_id}/qa/suggestions`：获取建议追问。
- `GET /api/demo-report`：返回离线 demo 报告。

`GET /api/reports/{report_id}/result` 的核心字段包括：

- `summary`：变更摘要、风险概览、评审重点。
- `file_risks`：文件风险等级、分数、原因、维度和 patch。
- `findings`：问题标题、等级、置信度、文件、行号、证据、影响、建议。
- `test_suggestions`：测试补充建议。
- `generated_artifacts`：PR 标题/类型/labels、描述、walkthrough、changelog、改进建议、文档建议、相似历史项。
- `context_summary` / `review_context`：上下文收集覆盖情况。
- `github_comment_markdown`：可复制的评论预览。

## 设计说明

### 模型与降级

- Fast 模式主要关注 P0/P1 严重问题。
- Standard 模式聚焦高风险文件。
- Deep 模式覆盖更多文件和审查维度。
- 强模型超时时会尝试快模型重试；LLM 不可用时降级到规则分析。
- 提示词要求除代码、路径、枚举值、URL、label 名称外，所有解释性字段尽量使用简体中文。

### 上下文与大 PR

- 风险分类器先基于文件路径、diff 规模、行为关键词、测试信号和上下文信号给文件排序。
- 上下文收集器会补充 changed hunk 周边代码、函数/类片段、相关测试、README/docs、配置文件和轻量历史 issue/PR。
- Diff budgeter 会根据模式和风险分配 review 输入预算，避免大 PR 直接截断掉全部后续文件。

### 误报控制

- finding 必须有文件、变更行、证据、影响、建议和置信度。
- verifier 会过滤非变更文件、非变更行、证据不足、置信度过低和重复 findings。
- 风格类建议会降级为 P3 / `[建议]`，真实发布前只提供 dry-run Markdown 预览。

## 测试

后端：

```powershell
cd backend
$env:PYTHONPATH='.'
pytest
```

前端构建检查：

```powershell
cd frontend
npm run build
```

常用合并前检查：

```powershell
cd backend
$env:PYTHONPATH='.'
pytest
cd ..\frontend
npm run build
```

测试覆盖 PR URL 解析、GitHub client、diff 解析、diff budgeter、风险分类、pattern analyzer、finding verifier、上下文收集、报告服务、artifact generator、OpenAI provider 和 CORS。

## 演示流程

1. 启动后端和前端。
2. 输入公开 GitHub PR URL，选择快速/标准/深度模式，点击“开始分析”。
3. 观察进度；需要时可以取消或对失败报告重试。
4. 查看摘要、上下文覆盖、风险文件、具体 findings、测试建议、PR 准备稿和相似历史项。
5. 使用“追问与交互”询问风险原因、请求修复代码或生成测试。
6. 复制 GitHub 评论预览或 artifacts 预览，作为 dry-run 内容人工确认后再发布。

## 已知注意事项

- 未配置 `GITHUB_TOKEN` 时，GitHub 匿名 API 很容易触发 `403 rate limit exceeded`。
- 旧报告内容已经写入 SQLite，不会因提示词或模板修改自动更新；需要重新分析才能得到新输出。
- 当前 `comment` API 只返回预览 Markdown，不会自动写回 GitHub。
- 不要提交 `.env`、虚拟环境、SQLite 数据库、`node_modules` 或构建产物。

## Docker 部署

项目通过 `docker compose` 编排两个服务：**backend**（FastAPI + uvicorn，端口 8765）和 **frontend**（Nginx 静态服务 + 反向代理，端口 80）。前端 Nginx 将 `/api/` 和 `/health` 请求代理到 backend 容器，无需分别暴露后端端口。

### 前置条件

- Docker Engine 24+ 及 `docker compose` 插件（或 Docker Desktop）
- （可选）GitHub Personal Access Token 和 LLM API Key，用于完整 AI 审查功能；无凭证时系统会自动降级

### 配置

在仓库根目录准备 `.env` 文件（可参照 `backend/.env.example`）：

```env
# 服务端口（宿主机映射端口，默认 8080）
APP_PORT=8080

# GitHub 与 LLM（不配置则降级为规则分析 / 离线演示）
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
LLM_API_KEY=sk-xxxxxxxxxxxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_FAST=gpt-4.1-mini
LLM_MODEL_STRONG=gpt-4.1
LLM_MODEL_MULTIMODAL=gpt-4.1

# LLM 超时与重试
LLM_TIMEOUT_SECONDS=180
LLM_RETRY_TIMEOUT_SECONDS=90

# Q&A 参数
LLM_QA_TEMPERATURE=0.3
LLM_MAX_CONTEXT_MESSAGES=20

# 分析容量限制
MAX_FILES=80
MAX_PATCH_CHARS=14000
MAX_CONTEXT_FILES=20
MAX_CONTEXT_FILE_CHARS=40000
MAX_RELATED_FILES=12
MAX_HISTORY_ITEMS=10
MAX_GITHUB_PAGES=4

# Docker 内部使用 /data 目录持久化 SQLite
DATABASE_URL=sqlite:////data/ai_pr_review.db

# 生产环境应关闭 localhost CORS 宽松策略
ALLOW_LOCALHOST_DEV_ORIGINS=false
```

`docker-compose.yml` 中所有环境变量均设有合理默认值，无需全量填写即可启动。

### 构建与启动

```bash
# 在仓库根目录执行
docker compose up --build -d
```

首次构建会安装依赖并编译前端，耗时约 1–3 分钟。之后可直接使用：

```bash
docker compose up -d
```

### 访问

浏览器打开 `http://127.0.0.1:8080`（或自定义的 `APP_PORT`）。如果后端、GitHub 或 LLM 暂不可用，可以点击"加载演示"查看离线报告。

### 常用操作

```bash
docker compose logs -f              # 实时查看日志
docker compose logs backend         # 仅查看后端日志
docker compose restart              # 重启所有服务
docker compose down                 # 停止并删除容器（保留数据卷）
docker compose down -v              # 停止并删除容器 + 数据卷（清空数据库）
docker compose pull                 # 拉取基础镜像更新
docker compose up -d --build        # 重新构建并启动
```

### 架构说明

- **前端**：多阶段构建 — 第一阶段用 `node:22-alpine` 执行 `npm ci` + `npm run build`，第二阶段用 `nginx:1.27-alpine` 托管静态产物。Nginx 配置 (`frontend/nginx.conf`) 同时承担 SPA 路由回退和 `/api/` 反向代理。
- **后端**：基于 `python:3.12-slim`，通过 `uvicorn` 在容器内 `0.0.0.0:8765` 监听。`/health` 端点供 Docker healthcheck 探活。
- **数据持久化**：SQLite 数据库存储在命名卷 `backend-data` 中，映射到容器内 `/data` 目录。`docker compose down` 不会删除该卷，除非加 `-v` 参数。
- **网络**：两个服务共享 Compose 默认网络，前端通过服务名 `backend` 解析后端地址，无需公网暴露后端端口。

## 在线部署

项目已部署至：http://dearxzh.asia:7989/

## 演示视频

- 百度云盘：https://pan.baidu.com/s/1mKfZr5FGiIxXJt0KHAy-Qg?pwd=jqw4
- QQ 闪传：https://qfile.qq.com/q/fsBRKUThQs
