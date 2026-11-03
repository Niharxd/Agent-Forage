# AgentForge backend

The backend is a FastAPI application using PostgreSQL as its durable data
store. SQLAlchemy 2.x models live in `app/agentforge/domain/models/`; Alembic
migrations live in `migrations/`.

## Requirements and environment

- Python 3.11–3.14
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 or newer (or Docker Desktop)

From the repository root, copy the environment template and set a local
password for PostgreSQL in `.env`. Use URL-encoded characters if the password
contains reserved URL characters.

```powershell
Copy-Item .env.example .env
python -m uv --directory backend sync --all-groups
```

`DATABASE_URL` is the application PostgreSQL connection string and
`TEST_DATABASE_URL` must refer to the separate `agentforge_test` database.
Both URLs must use the `postgresql+psycopg` SQLAlchemy driver. The test suite
refuses any test URL that is not local, does not target `agentforge_test`, or
matches the application URL. `APP_ENV=test` selects `TEST_DATABASE_URL` for
the application and migration commands.

Authentication has not been specified for this single-operator MVP, so the
`users` table intentionally has no password field. Do not expose this service
to an untrusted network without an approved authentication mechanism.

## Start the local database

The supplied Compose service binds PostgreSQL to loopback only and creates
both `agentforge` and `agentforge_test` databases on first initialization.
Run from the repository root after setting `POSTGRES_PASSWORD` in `.env`:

```powershell
docker compose --env-file .env -f backend/docker-compose.yml up -d db
docker compose --env-file .env -f backend/docker-compose.yml ps
```

If a PostgreSQL instance is already available, create an isolated test
database named `agentforge_test` owned by the application role. Do not point
the test URL at the development or production database.

## Migrations

Run all database commands from the repository root. Alembic loads its
connection URL from application settings and imports the model metadata for
autogeneration.

```powershell
python -m uv --directory backend run alembic upgrade head
python -m uv --directory backend run alembic current
```

Create a migration after changing the SQLAlchemy models, then review and apply
it:

```powershell
python -m uv --directory backend run alembic revision --autogenerate -m "describe schema change"
python -m uv --directory backend run alembic upgrade head
```

Rollback one migration with:

```powershell
python -m uv --directory backend run alembic downgrade -1
```

To apply or roll back migrations against the isolated test database, select
test mode first:

```powershell
$env:APP_ENV = "test"
python -m uv --directory backend run alembic upgrade head
Remove-Item Env:APP_ENV
```

## Tests and checks

The database integration tests use PostgreSQL features including UUID and
JSONB, so they do not substitute SQLite. They migrate and clean up only the
database named `agentforge_test`. Set test mode and execute:

```powershell
$env:APP_ENV = "test"
python -m uv --directory backend run pytest
python -m uv --directory backend run ruff check app tests migrations
Remove-Item Env:APP_ENV
```

The API liveness endpoint does not require the database. Request handlers can
inject a request-scoped SQLAlchemy `Session` with
`agentforge.database.dependencies.get_db_session`; its transaction is rolled
back when left uncommitted.

## Run the API

```powershell
python -m uv --directory backend run uvicorn agentforge.main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Configure secrets only in local
environment variables or an untracked `.env`; never commit credentials or
include them in logs.

## Agent contracts (Day 6)

Provider-neutral Pydantic contracts live in
`app/agentforge/domain/agents/`; implementations live in
`app/agentforge/agents/`. `AgentInput` carries a bounded task description,
workflow context, supplied data, optional prior results, metadata, requested
capabilities, and review criteria. `AgentIdentity` declares an agent's stable
identifier, role, description, version, and supported capabilities.
`AgentOutput` contains structured JSON-compatible result data, a summary,
metadata, status, and a categorized error when it fails. `AgentExecutionResult`
adds duration and optional token usage. These contracts do not depend on
FastAPI, SQLAlchemy, or an LLM provider SDK.

Each implementation exposes the same synchronous `Agent` interface:
`identity`, `supported_capabilities`, `validate_input`, and `execute`.
Invalid inputs, unsupported capabilities, implementation failures, and invalid
outputs return a failed execution result with a stable error category.

The four deterministic mocks have intentionally narrow responsibilities:

- **Planner:** creates a single-step draft marked non-executable; it does not
  validate or run a workflow.
- **Researcher:** returns supplied information and prior results without
  network access, external sources, or added findings.
- **Analyst:** describes top-level JSON field types only; it does not infer
  trends, validate domain meaning, or add external facts.
- **Reviewer:** checks literal, case-insensitive criterion presence in supplied
  material; it does not assess semantic correctness or quality.

All mocks are deterministic and provider-free. They do not execute workflows,
coordinate with one another, perform real research, or call external services.

## Deterministic workflow execution (Day 7)

The in-memory `agentforge.workflow.WorkflowEngine` connects workflow tasks to
the existing four agents through their provider-neutral synchronous `Agent`
interface. A workflow contains declarative tasks with an ID, agent role,
JSON input, optional description, review criteria, and dependency IDs. It
contains no executable code.

The engine validates the complete definition before execution: it requires at
least one task, unique IDs, known agent roles and dependencies, no
self/duplicate dependencies, an acyclic graph, and no more than 25 tasks.
Callers can lower that limit by constructing
`WorkflowValidator(max_tasks=...)`. Task input is limited to 10,000 serialized
bytes. Invalid workflows raise `WorkflowValidationError` with structured
issues and are never dispatched.

Tasks execute sequentially in deterministic topological order, with task IDs
breaking ties among ready tasks. A task receives only the successful outputs
of its direct dependencies. On agent failure, the task is recorded as failed;
its dependent tasks are blocked and independent tasks continue. Any failed or
blocked task makes the workflow fail. The returned Pydantic execution result
contains task statuses, agent results/errors, UTC lifecycle events, and
completion timestamps.

The engine uses deterministic Day 6 mock agents only. The Planner creates a
non-executable draft, the Researcher only returns supplied information, the
Analyst reports JSON field types, and the Reviewer checks literal criterion
presence. No real LLM, tool, filesystem, shell, or internet integration is
invoked. Execution state and events are currently in memory only: this
milestone does not add API endpoints, database persistence, migrations,
parallelism, retries, or worker infrastructure. Per-attempt timeout enforcement
and restart recovery are also not implemented.

Example:

```python
from agentforge.domain.agents import AgentRole
from agentforge.domain.workflows import WorkflowDefinition, WorkflowTask
from agentforge.workflow import WorkflowEngine

definition = WorkflowDefinition(
    name="inspect supplied data",
    tasks=[
        WorkflowTask(
            task_id="inspect",
            agent_type=AgentRole.ANALYST,
            input_data={"count": 3, "labels": ["a", "b"]},
            description="Describe the supplied data structure.",
        )
    ],
)
execution = WorkflowEngine().execute(definition)
print(execution.status, execution.task_results["inspect"].agent_result.output.summary)
```
