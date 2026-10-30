# AgentForge

AgentForge is a self-hosted application for turning a task into an inspectable,
validated workflow. The approved scope, architecture, roadmap, and threat model
are documented in [`docs/`](docs/).

The initial backend milestone provides a versioned FastAPI health API,
environment-backed settings, and standardized error responses. Workflow
execution, persistence, provider integrations, authentication, and dashboard
features have not been implemented.

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
environment-backed settings. `database/` is reserved for persistence and
migrations; `domain/models/` for domain entities; `workflow/` for orchestration;
and `agents/`, `tools/`, and `providers/` for their respective interfaces and
adapters.

The frontend source lives under `frontend/src/`: `components/` for reusable UI,
`pages/` for screens, `api/` for API clients, `hooks/` for shared React hooks,
`types/` for TypeScript contracts, and `styles/` for global styling. The
current page is only a build/test scaffold.

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
cross-origin access. The database URL is not used by this milestone. Do not
commit `.env` or put real credentials in it when sharing logs or examples.

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

`GET /api/v1/ready` reports API readiness separately. No database or external AI
dependencies are initialized or checked in this milestone.

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
