# AgentForge

AgentForge is a self-hosted application for turning a task into an inspectable,
validated workflow. The approved scope, architecture, roadmap, and threat model
are documented in [`docs/`](docs/).

This repository currently contains the monorepo and package scaffolding only.
Workflow execution, API behavior, persistence, provider integrations, and
dashboard features have not been implemented.

## Repository layout

| Path | Purpose |
| --- | --- |
| `backend/` | Python backend package and its package-level tests. |
| `frontend/` | React, Vite, and TypeScript dashboard package. |
| `docs/` | Approved product, architecture, roadmap, and threat-model documents. |
| `scripts/` | Home for repeatable local development and maintenance scripts. |
| `tests/` | Reserved for cross-package integration tests. |
| `.github/workflows/` | Continuous-integration workflows. |

Within `backend/app/agentforge/`, `api/routes/` is reserved for HTTP endpoints;
`config/` for environment-backed settings; `database/` for persistence and
migrations; `domain/models/` for domain entities; `workflow/` for orchestration;
and `agents/`, `tools/`, and `providers/` for their respective interfaces and
adapters. These modules are intentionally empty at this milestone.

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

The `.env` file is a local placeholder for future runtime configuration; replace
the database URL placeholders only with local values. Do not commit `.env` or
put real credentials in it when sharing logs or examples.

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
