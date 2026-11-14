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

The backend protects approval listing and review with its shared operator
bearer token. There is no secure browser session or server-side token proxy in
the current architecture, so the frontend does not embed or store that token.
Approval review remains unavailable from the browser until a server-side
authentication boundary is provided; protected approval reads show the API's
safe error. Do not add the token to `VITE_*` variables because those values are
bundled into browser code.

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
