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

## API integration and operator authentication

The frontend calls the same-origin `/api/v1` routes. Vite proxies `/api` to
`http://127.0.0.1:8000` during local development. The UI uses persisted
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

## Theme implementation

The application uses a centralized theme provider and stores the selected preference in `localStorage` with support for light, dark, and system themes. The theme is applied to the `document.documentElement` and the active theme is reused across all routes.

## Route structure

- `/` — Dashboard
- `/workflows` — Workflow registry
- `/agents` — Agent directory
- `/tools` — Tool registry
- `/executions` — Execution history
- `/settings` — Appearance and application settings
