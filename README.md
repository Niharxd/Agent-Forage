# AgentForge

AgentForge is a self-hosted application for turning a task into an inspectable,
validated workflow. The approved scope, architecture, roadmap, and threat model
are documented in [`docs/`](docs/).

The backend provides versioned workflow and execution APIs, PostgreSQL-backed
workflow/execution history, a bounded sequential engine, and a React dashboard
with execution history and dependency-graph visualization. Mock agents remain
the default. Day 15 adds an optional OpenAI Planner adapter and an explicitly
requested, read-only Wikipedia search tool.

## Repository layout

| Path | Purpose |
| --- | --- |
| `backend/` | Python backend package and its package-level tests. |
| `frontend/` | React, Vite, and TypeScript dashboard package. |
| `docs/` | Approved product, architecture, roadmap, and threat-model documents. |
| `scripts/` | Home for repeatable local development and maintenance scripts. |
| `tests/` | Reserved for cross-package integration tests. |
| `.github/workflows/` | Continuous-integration workflows. |

Within `backend/app/agentforge/`, `main.py` creates the FastAPI application,
`api/routes/` contains versioned HTTP endpoints, and `config/` contains
environment-backed settings. `database/` and `domain/models/` provide
PostgreSQL persistence and SQLAlchemy models; `workflow/` contains the bounded
orchestration engine; and `agents/`, `tools/`, and `providers/` contain their
respective interfaces and adapters. See [`backend/README.md`](backend/README.md)
for database setup and migration commands.

The frontend source lives under `frontend/src/`: `components/` for reusable UI,
`pages/` for screens, `api/` for API clients, `theme/` for theme state, and
`styles/` for global styling.

## Prerequisites

- Python 3.11 through 3.14
- [uv](https://docs.astral.sh/uv/)
- Node.js 22.12 or newer and npm

Install uv if it is not already available:

```powershell
python -m pip install --user uv
```

## Windows PowerShell setup

Run these commands from the repository root:

```powershell
Copy-Item .env.example .env
python -m uv --directory backend sync --all-groups
npm --prefix frontend ci
```

The `.env` file contains local runtime configuration. `CORS_ORIGINS` is a JSON
array of explicitly allowed HTTP(S) origins; leave it empty (`[]`) to disable
cross-origin access. Configure the database URLs and start PostgreSQL as
described in [`backend/README.md`](backend/README.md). Do not commit `.env` or
put real credentials in it when sharing logs or examples.

Provider use is opt-in. Keep `PROVIDER_MODE=mock` for deterministic, offline
operation. To use the OpenAI Planner adapter, set `PROVIDER_MODE=openai` and
provide `OPENAI_API_KEY` and a long random `API_ACCESS_TOKEN`;
`OPENAI_MODEL` and `OPENAI_TIMEOUT_SECONDS` have safe defaults. Workflow and
execution API routes require that bearer token while OpenAI mode is enabled;
health endpoints remain public. Only the Planner task description is sent to
OpenAI, and only after explicit workflow start. A `wikipedia_search` tool
request sends its bounded query to English Wikipedia after start. Neither
integration accepts arbitrary URLs; do not submit credentials or other
sensitive data as task/query content. No provider credentials are needed for
tests.

## Start the backend

From the repository root, start the API with:

```powershell
python -m uv --directory backend run uvicorn agentforge.main:app --reload
```

The local liveness endpoint is `http://127.0.0.1:8000/api/v1/health` and returns:

```json
{
  "status": "ok",
  "service": "agentforge-api",
  "version": "v1",
  "checks": {
    "liveness": "ok"
  }
}
```

`GET /api/v1/ready` reports API readiness separately. The application creates
and disposes its SQLAlchemy engine with the FastAPI lifespan; connections are
opened when a database session is used.

## Checks

Run the backend tests and lint check:

```powershell
python -m uv --directory backend run pytest
python -m uv --directory backend run ruff check .
```

Run the frontend tests, type check, and production build:

```powershell
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

## Dependency management

- Python dependencies are declared in `backend/pyproject.toml` with bounded
  compatible version ranges and resolved in the committed `backend/uv.lock`.
  Use `python -m uv --directory backend sync --all-groups` to install the
  locked application and development dependencies.
- Frontend dependency versions are recorded in `frontend/package-lock.json`.
  Use `npm --prefix frontend ci` for a reproducible install; update
  dependencies with npm and commit both the manifest and lockfile.

## Licensing

No license has been selected. The root [`LICENSE`](LICENSE) records that no
license grant is made while the maintainers decide. Do not assume the code is
available for reuse or distribution; replace the notice with the approved
license before making such a grant.
