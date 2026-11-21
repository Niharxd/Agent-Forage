# AgentForge Frontend

The AgentForge frontend is a React + TypeScript + Vite application built as a polished SaaS-style interface for an autonomous AI workflow orchestration platform.

## Technology

- React 19
- TypeScript
- Vite
- Tailwind CSS
- React Router DOM
- Lucide React

## Installation

From the `frontend` directory:

```bash
npm install
```

## Development startup

```bash
npm run dev
```

## Build commands

```bash
npm run build
npm run typecheck
```

## Test commands

```bash
npm run test
```

The production image is built with `Dockerfile` and served by Nginx using
`nginx.conf`. The Nginx configuration serves the SPA fallback and proxies
`/api` to the Compose backend service. Build-time `VITE_API_BASE_URL` defaults
to `/api/v1`; it must remain relative for this same-origin setup.

## API integration and operator authentication

The frontend calls the configurable `VITE_API_BASE_URL` in local and
non-production builds (default `/api/v1`). Production builds always use
`/api/v1` so browser requests stay same-origin. Vite proxies `/api` to
`http://127.0.0.1:8000` during local development. The Vercel deployment uses
`frontend/vercel.json` to rewrite `/api/v1/*` to the Render API. The UI uses persisted
workflow and execution APIs for workflow preparation, workflow listing,
execution history, details, start, cancellation, and approval visibility.

The application restores its authenticated state through
`GET /api/v1/auth/session`. Operators submit the shared credential to
`POST /api/v1/auth/session`; the API verifies it and returns an HttpOnly,
SameSite=Strict session cookie. The input is cleared after submission and the
credential is never stored in browser storage or frontend configuration.
`DELETE /api/v1/auth/session` revokes the process-local session. In OpenAI
mode and production, the cookie authenticates workflow, execution, and approval
requests. Cookie-authenticated state-changing requests require an exact
configured `Origin`. The frontend asks for confirmation and waits for the API
response before reporting a decision, then reloads approvals and execution
details. Approval summaries contain only safe descriptions and identifiers.

The API and UI must share a browser origin in deployment; route `/api` through
a reverse proxy to FastAPI. Set `CORS_ORIGINS` to that exact UI origin.
Production requires HTTPS and sets
the cookie `Secure` flag. The backend still accepts its existing bearer token
for protected API use. Session revocation is process-local, so use a single API
process; a restart expires all sessions. Do not add the token to `VITE_*`
variables because those values are bundled into browser code.

The official `AgentForge Gradient Circuit Logo.png` is stored at
`public/assets/agentforge-logo.png` and used in the sidebar with contained
proportions. Its supplied transparency and gradient are preserved.

Submitted task descriptions are persisted by the backend. Do not submit
credentials or content that must not be retained.

## Dependency security note

The production dependency graph currently uses Vite 6.4.6, which resolves
`vite -> tinyglobby@0.2.17 -> fdir@6.5.0 -> picomatch@4.0.7`.
`npm audit --omit=dev` reports `GHSA-fc5q-39xc-vjpf` against picomatch
(`<=4.0.7`, high severity ReDoS). No patched picomatch release is published,
and Vite 7.x and 8.x retain the same dependency range. npm's suggested Vite
6.2.7 workaround has separate Vite vulnerabilities and is not used. Re-run
both npm audit commands when Vite, tinyglobby, fdir, or picomatch releases
change; do not add an override unless a published patched version passes the
frontend test, typecheck, and build checks.

To point a separately hosted frontend at an API, set `VITE_API_BASE_URL` at
build time (for example, `https://api.example.invalid/api/v1`). This value is
public browser configuration; never put credentials or tokens in `VITE_*`
variables.

## Theme implementation

The application uses a centralized theme provider and stores the selected preference in `localStorage` with support for light, dark, and system themes. The theme is applied to the `document.documentElement` and the active theme is reused across all routes.

## Route structure

- `/` — Dashboard
- `/workflows` — Workflow registry
- `/agents` — Agent directory
- `/tools` — Tool registry
- `/executions` — Execution history
- `/settings` — Appearance and application settings
