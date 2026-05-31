# Docker 一键部署

这个项目现在可以用 Docker Compose 同时启动 FastAPI 后端和 React 前端。前端容器使用 Nginx 托管静态文件，并把 `/api`、`/health` 反向代理到后端容器，所以浏览器只需要访问一个地址。

## 快速启动

```powershell
copy .env.docker.example .env
docker compose up --build
```

启动后打开：

```text
http://127.0.0.1:8080
```

没有配置 `GITHUB_TOKEN` 或 `LLM_API_KEY` 时，项目仍然可以使用规则分析和离线 demo 数据。

## 常用配置

编辑仓库根目录的 `.env`：

```env
APP_PORT=8080
GITHUB_TOKEN=
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_FAST=gpt-4.1-mini
LLM_MODEL_STRONG=gpt-4.1
DATABASE_URL=sqlite:////data/ai_pr_review.db
```

默认 SQLite 数据库保存在 Docker volume `backend-data` 中。查看 volume：

```powershell
docker volume ls
```

停止服务：

```powershell
docker compose down
```

如果想连数据库数据也一起删除：

```powershell
docker compose down -v
```

## 生产部署提示

- 对外只需要暴露 `APP_PORT` 对应的前端端口。
- 反向代理或网关可以转发到 `http://服务器地址:APP_PORT`。
- 不要把 `.env`、SQLite 数据库、`node_modules`、`dist` 或虚拟环境提交到 Git。
- 如果部署在远程服务器，保持 `VITE_API_BASE_URL` 为空，让前端使用同源 `/api`，避免浏览器访问错误的本机 `127.0.0.1`。

