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

## Environment variables

The frontend uses a centralized API configuration pattern and supports a base URL environment variable:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

The app does not implement live workflow execution yet, so all workflow and execution screens use development demo data until backend integration is connected.

## Theme implementation

The application uses a centralized theme provider and stores the selected preference in `localStorage` with support for light, dark, and system themes. The theme is applied to the `document.documentElement` and the active theme is reused across all routes.

## Route structure

- `/` — Dashboard
- `/workflows` — Workflow registry
- `/agents` — Agent directory
- `/tools` — Tool registry
- `/executions` — Execution history
- `/settings` — Appearance and application settings
