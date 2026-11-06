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

All mocks are deterministic and provider-free. Planner drafts do not execute by
themselves. `WorkflowOrchestrator` prepares a validated pending workflow from a
Planner draft; execution still requires an explicit `start()` call.

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
presence. `WorkflowOrchestrator.prepare()` converts ordered Planner steps to a
declarative workflow and registers it through the normal workflow validator.
It returns a pending execution; call `start(execution_id)` to run it. Optional
review criteria add a final Reviewer task. A `failed` or `not_evaluated`
verdict makes the workflow fail rather than returning success.

Workflow tasks may include one optional `tool_request` with a registered tool
ID and JSON arguments. On preparation, the engine verifies tool registration,
enablement, agent capabilities, schema, and input bounds without invoking the
handler. On start, tools run only through `ToolExecutor`, using capabilities
from the selected agent's identity. Successful tool output is supplied only to
direct dependent tasks; denied or failed tool calls fail the task and block
dependents. Planner output cannot declare tools. Tool failure results omit raw
handler exception text.

No real LLM, filesystem, shell, or internet integration is invoked. Execution
state and events remain in memory. This integration does not add API endpoints,
database persistence, migrations, parallelism, retries, worker infrastructure,
or restart recovery. Tool execution is synchronous; elapsed-time limits are
checked after a handler returns and cannot interrupt a stuck handler. The
current tool contract has no risk-classification or approval/resume workflow,
so this integration enforces registration, capability, schema, and size policy
but does not claim approval gating for side effects.

Example:

```python
from agentforge.workflow import WorkflowOrchestrator

orchestrator = WorkflowOrchestrator()
prepared = orchestrator.prepare(
  "inspect the supplied labels",
  input_data={"labels": ["alpha", "beta"]},
  review_criteria=["observations"],
)
execution = orchestrator.start(prepared.execution.execution_id)
print(execution.status)
```

## Tool registry and safe execution (Day 9)

The backend ships a provider-neutral `agentforge.tools` package for explicit,
permissioned tool execution. The package contains:

- `ToolDefinition`, `ToolInput`, `ToolOutput`, `ToolExecutionRequest`,
  `ToolExecutionResult`, `ToolExecutionStatus`, and `ToolExecutionError`.
- `ToolRegistry` for in-memory registration, lookup, capability filtering, and
  enable/disable policy.
- `ToolExecutor` for permission checks, schema validation, trusted handler
  invocation, and safe result/error reporting.
- A default registry with three deterministic safe tools: `text_analysis`,
  `json_inspection`, and `calculator`.

The executor accepts an explicit `agent_id` and explicit capability context, not
just a free-form tool name. A handler must already be registered in trusted
application code; the tool system never imports arbitrary modules or executes
Python, shell, or SQL from untrusted strings. Calls are denied when the tool is
missing, disabled, or outside an agent's declared capability set. Results must
match the declared output schema and remain within the configured byte limits.

This is a deny-by-default policy layer. The executor will not run a tool whose
handler is missing, non-callable, or not in the registry. It records a safe,
structured failure rather than disclosing internal exceptions. Hard timeout
cancellation of a synchronous Python handler is not safe without process or
worker isolation: the executor can only enforce configured limits after a
handler returns and must fail closed when the measured execution exceeds the
configured budget.

## Execution reliability and state (Day 8)

The engine applies explicit transitions and rejects invalid ones:

- Workflow: `PENDING -> RUNNING | CANCELLED`; `RUNNING -> COMPLETED | FAILED | CANCELLED`.
- Task: `PENDING -> RUNNING | BLOCKED | SKIPPED`; `RUNNING -> COMPLETED | FAILED`.
- Terminal workflow/task states cannot be restarted. Failed tasks and dependency-blocked tasks remain distinct; independent tasks continue after failures.

`WorkflowEngine.create_execution()` validates and returns a pending
`WorkflowExecutionSnapshot` without invoking an agent. `run(execution_id)`
executes that pending run; the existing `execute(definition)` remains the
synchronous create-and-run convenience method. Snapshots contain the execution
ID, workflow name, status, timestamps, task results/errors, structured events,
and deterministic task start order. They are Pydantic models and serialize
with `model_dump_json()`.

Pending workflows can be cancelled immediately; their tasks are marked
`SKIPPED`. Cancellation of a running workflow is cooperative and takes effect
between tasks. A synchronous mock-agent call already in progress is allowed to
return normally; its result is retained, no subsequent task starts, and the
remaining pending tasks are skipped. The engine does not claim hard
interruption of an active call.

The engine loads limits from `Settings` and the matching environment variables:
`WORKFLOW_MAX_TASKS` (25), `WORKFLOW_MAX_EXECUTION_STEPS` (25),
`WORKFLOW_MAX_TASK_INPUT_BYTES` (10,000),
`WORKFLOW_MAX_RESULT_BYTES` (100,000), and `WORKFLOW_HISTORY_SIZE` (100).
The settings enforce safe upper bounds. Oversized task input is rejected before
agent dispatch; an oversized result fails without being retained. Reaching the
execution-step limit skips remaining runnable tasks and fails the workflow.

Failed-task results retain the task ID, agent role, stable error category,
safe user-facing message, and error timestamp. Raw exception text and failed
agent payloads are not included in returned execution state. Developers still
receive structured log context with IDs, agent role, category, and exception
class.

Terminal snapshots are kept in a bounded in-memory history. `get_execution(id)`
returns a detached snapshot or raises `ExecutionNotFoundError`;
`list_executions(limit=...)` returns recent terminal executions newest first.
Returned snapshots cannot mutate stored history. History, active executions,
and cancellation requests are process-local and are lost on restart. There
are no Day 8 API endpoints, database writes/migrations, retries, worker
coordination, or restart recovery.

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
