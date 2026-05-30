# AGENTS.md

## Project Overview

This repository is an AI-assisted GitHub Pull Request review demo. It provides:

- A FastAPI backend for PR fetching, risk classification, review generation, and report APIs.
- A React + TypeScript + Vite frontend for entering a PR URL and viewing the analysis report.
- A GitHub Action sample for calling the backend in PR workflows.
- Offline demo data so the UI can be demonstrated even without GitHub or LLM credentials.
- Context collection, pattern-based static analysis, and verification layers for deeper review output.

## Repository Layout

```text
backend/
  app/
    main.py                  # FastAPI app entrypoint and CORS setup
    api/                     # Analysis, report, and demo route modules
    analyzer/                # Context collection, diff parsing, risk classification, review, verification
      context_collector.py   # Related file, docs, config, and history context collection
      pattern_analyzer.py    # Regex-based static bug and security pattern detection
      service.py             # Report lifecycle orchestration and persistence
    db/                      # SQLite/SQLAlchemy storage and lightweight migrations
    github/                  # GitHub PR URL parser and REST client/context helpers
    llm/                     # OpenAI-compatible provider abstraction
    models/                  # Pydantic schemas
  tests/                     # Backend tests
  requirements.txt

frontend/
  src/
    main.tsx                 # Main React UI
    styles.css               # Demo styling
    api/                     # API client
    data/                    # Offline demo report
    types/                   # Shared TypeScript report types
  package.json

action/
  action.yml                 # Composite GitHub Action sample

.github/workflows/
  ai-pr-review.yml           # Example workflow
```

## Backend Setup

Run commands from the repository root unless noted otherwise.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

Use `python -m uvicorn` instead of bare `uvicorn` so the active virtual environment is used.

Optional environment file:

```powershell
copy .env.example .env
```

Relevant environment variables:

- `GITHUB_TOKEN`: optional token for private repos or higher GitHub API rate limits.
- `LLM_API_KEY`: optional OpenAI-compatible API key.
- `LLM_BASE_URL`: defaults to `https://api.openai.com/v1`.
- `LLM_MODEL_FAST`: fast summary/risk model. Default: `gpt-4.1-mini`.
- `LLM_MODEL_STRONG`: stronger review model. Default: `gpt-4.1`.
- `LLM_TIMEOUT_SECONDS`: request timeout for normal LLM calls.
- `LLM_RETRY_TIMEOUT_SECONDS`: shorter timeout for retry paths.
- `DATABASE_URL`: optional database override; defaults to `backend/ai_pr_review.db`.
- `MAX_FILES`, `MAX_PATCH_CHARS`: limits for fetched PR files and patch text.
- `MAX_CONTEXT_FILES`, `MAX_CONTEXT_FILE_CHARS`, `MAX_RELATED_FILES`, `MAX_HISTORY_ITEMS`, `MAX_GITHUB_PAGES`: context collection limits.
- `ALLOW_LOCALHOST_DEV_ORIGINS`: keep local Vite origins allowed during development.

If no LLM key is configured, the app should still provide rule-based analysis and demo output.

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

Default backend URL is `http://127.0.0.1:8000` unless overridden with:

```env
VITE_API_BASE_URL=http://127.0.0.1:8765
```

If the backend is unavailable, use the UI's `Load demo` path where available.

## Testing

Backend tests:

```powershell
cd backend
$env:PYTHONPATH='.'
pytest
```

If `pytest` is not found, install dependencies first:

```powershell
pip install -r requirements.txt
```

Frontend build check:

```powershell
cd frontend
npm run build
```

Useful smoke checks before merging backend/frontend changes:

```powershell
cd backend
$env:PYTHONPATH='.'
pytest
cd ..\frontend
npm run build
```

## API Surface

- `POST /api/analyze-pr`: create an asynchronous analysis report.
- `GET /api/reports`: list recent reports.
- `GET /api/reports/{report_id}`: poll report status.
- `GET /api/reports/{report_id}/events`: stream report status with SSE.
- `GET /api/reports/{report_id}/result`: fetch the completed report.
- `POST /api/reports/{report_id}/retry`: retry a report.
- `POST /api/reports/{report_id}/cancel`: request cancellation.
- `POST /api/reports/{report_id}/comment`: return dry-run comment markdown.
- `GET /api/demo-report`: return the offline demo report.

## Git And Push Notes

This workspace may require a safe-directory override because of sandbox ownership:

```powershell
git -c safe.directory=D:/AFile/CodeXProject/AI-PR-Review status
```

If GitHub HTTPS push fails while normal API access works, configure the repo-local proxy:

```powershell
git config http.proxy socks5h://127.0.0.1:10808
git config https.proxy socks5h://127.0.0.1:10808
```

Then push:

```powershell
git -c safe.directory=D:/AFile/CodeXProject/AI-PR-Review push
```

## Implementation Guidelines For Agents

- Keep the demo runnable even without GitHub or LLM credentials.
- Do not commit `.env`, virtual environments, SQLite databases, `node_modules`, or build output.
- Prefer small, focused changes over broad rewrites.
- Maintain the public API shape documented in `README.md` unless the user explicitly requests a breaking change.
- Keep review findings evidence-backed: file, line, impact, confidence, and suggestion should be present.
- Preserve the offline demo path because it is important for presentations.
- When changing backend behavior, add or update tests under `backend/tests/`.
- When changing frontend report shapes, update TypeScript types and demo data together.
- When changing API/report schemas, update backend Pydantic models, frontend TypeScript types, and offline demo data together.
- Keep SQLite lightweight migration helpers in `backend/app/db/session.py` compatible with existing local databases.
- `AGENTS.md` is tracked documentation and should not be ignored. `.claude/` is local tool state and should stay ignored.

## Known Local Issues

- On some Windows setups, `uvicorn` may fail with `WinError 10013` when binding to certain ports. Try another port such as `8765`, run PowerShell as administrator, or check local firewall/proxy software.
- A broken virtual environment may show an error like `Unable to create process using ... Python311\\python.exe`. Recreate `backend/.venv` if that happens.
