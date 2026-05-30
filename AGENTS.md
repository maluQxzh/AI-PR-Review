# AGENTS.md

## Project Overview

This repository is an AI-assisted GitHub Pull Request review demo. It provides:

- A FastAPI backend for PR fetching, risk classification, review generation, and report APIs.
- A React + TypeScript + Vite frontend for entering a PR URL and viewing the analysis report.
- A GitHub Action sample for calling the backend in PR workflows.
- Offline demo data so the UI can be demonstrated even without GitHub or LLM credentials.

## Repository Layout

```text
backend/
  app/
    main.py                  # FastAPI app entrypoint
    api/                     # API route modules in the full local version
    analyzer/                # Diff parsing, risk classification, review, verification
    db/                      # SQLite/SQLAlchemy storage in the full local version
    github/                  # GitHub PR URL parser and REST client
    llm/                     # OpenAI-compatible provider abstraction
    models/                  # Pydantic schemas
  tests/                     # Backend tests
  requirements.txt

frontend/
  src/
    main.tsx                 # Main React UI
    styles.css               # Demo styling
    api/                     # API client in the full local version
    data/                    # Offline demo report in the full local version
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
- `LLM_MODEL_FAST`: fast summary/risk model.
- `LLM_MODEL_STRONG`: stronger review model.

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

## Known Local Issues

- On some Windows setups, `uvicorn` may fail with `WinError 10013` when binding to certain ports. Try another port such as `8765`, run PowerShell as administrator, or check local firewall/proxy software.
- A broken virtual environment may show an error like `Unable to create process using ... Python311\\python.exe`. Recreate `backend/.venv` if that happens.

