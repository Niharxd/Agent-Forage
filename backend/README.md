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

## Workflow and execution REST API (Day 11)

All routes are under `/api/v1`. Workflow request bodies contain `name`,
optional `description`, and a `tasks` array using the domain workflow schema.
Task IDs, agent roles, dependencies, task input bounds, workflow size, and
registered-tool permissions are checked by the existing workflow engine and
validator. Requests are limited to 1 MiB. API responses use Pydantic schemas;
SQLAlchemy models and raw exception messages are not returned.

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/workflows/prepare` | Plan a bounded `task_description`, persist the versioned workflow and pending execution in one transaction, and return the draft for review. Does not start work. |
| `POST` | `/workflows` | Validate and persist a new workflow version. Returns its ID, definition, version, and timestamps. |
| `GET` | `/workflows?limit=50&offset=0` | List persisted workflow versions. |
| `GET` | `/workflows/{workflow_id}` | Retrieve one persisted workflow version. |
| `POST` | `/workflows/validate` | Validate the definition and tool permissions without persisting it; returns `valid` and safe issue codes/locations. |
| `POST` | `/workflows/{workflow_id}/executions` | Persist a pending execution and task records without invoking agents or tools. |
| `POST` | `/executions/{execution_id}/start` | Explicitly run pending work through the existing orchestrator and workflow engine. |
| `GET` | `/executions?limit=50&offset=0` | List persisted executions with database-backed pagination; optional `status` and case-insensitive `search` filters match workflow names or execution IDs. |
| `GET` | `/executions/{execution_id}` | Reconstruct execution status, lifecycle events, task-level results, and execution order from PostgreSQL. |
| `POST` | `/executions/{execution_id}/cancel` | Cancel pending work or request cooperative cancellation while running. |

Workflow definitions are stored in the existing PostgreSQL `workflows` table.
Creating another definition with the same name creates its next version under
the existing unique `(name, version)` constraint. The API does not introduce
another workflow or execution table.

`POST /workflows/prepare` accepts a non-blank task description of at most
10,000 characters. It uses the configured Planner (`mock` by default), returns
the persisted workflow definition and safe pending-execution projection, and
requires a separate `POST /executions/{execution_id}/start` request before any
workflow agent or tool runs. In OpenAI mode the existing bearer-token
requirement applies, and the Planner provider receives only the task
description. The submitted task remains in the existing execution record;
long planner objectives are visibly abbreviated to the workflow metadata
limit, without truncating task instructions.

### Execution persistence and lifecycle (Day 12)

The API persists executions using the existing `workflow_executions`,
`execution_steps`, and `execution_events` SQLAlchemy models. It stores the
referenced workflow ID/version, the initial pending state and timestamps, one
step record per workflow task, task inputs/results, safe failure messages, and
ordered lifecycle events. Event details are allowlisted and omit tool payloads
and nested failure details. Successful task outputs and workflow inputs are
stored for reconstruction; no general-purpose secret redactor or retention
policy exists, so do not submit credentials or data that must not persist. It
does not create duplicate persistence tables.

`WorkflowEngine` remains independent of SQLAlchemy and owns all transition
validation. It reports detached Pydantic snapshots through a callback; the
`ExecutionRepository` adapter in `app/agentforge/api/services/executions.py`
commits each state snapshot, task changes, and newly appended events together.
Execution creation commits the execution, task rows, and `workflow_created`
event in one transaction before the engine registers it. Event sequence numbers
preserve append order and prevent duplicate event writes. A database exception
rolls back the complete transaction and is surfaced as an API failure; the
engine does not retry tool or agent calls after a persistence failure.

Retrieval validates and reconstructs detached API snapshots from the workflow
definition, execution, task, and event rows. Listing and pagination are
database-backed, so retrieval continues to work after process-local engine
history has been replaced. API clients have no direct execution-state update
endpoint.

Starting work remains synchronous and blocks the HTTP request. Cancellation
while running is cooperative and takes effect between synchronous agent/tool
calls; it cannot interrupt a call already in progress. Persisted history
survives an API restart, but active/pending records are not rehydrated into the
engine and cannot be resumed or cancelled after restart. There is no worker,
automatic recovery, or exactly-once side-effect guarantee.

Database writes cannot be atomic with external agent/tool side effects. If an
agent/tool completes and its following persistence transaction fails, the
database remains at the last committed state and the API reports failure; the
side-effect outcome may be ambiguous and must not be automatically retried.

The Vite development server proxies `/api` to `http://127.0.0.1:8000`. Run the
backend on that address while using the live execution history screen. A
deployed frontend must route `/api` to the backend on the same origin.

The Day 12 migration adds the engine's `pending`/`completed` workflow and
`completed`/`blocked`/`skipped` task states to existing constraints and adds a
per-execution sequence to audit events. Existing tables are reused.

Invalid request/schema input returns `422`; missing workflow or execution IDs
return `404`; invalid execution transitions return `409`; request bodies above
1 MiB return `413`. Error responses use stable codes and omit raw Python
exception messages. The API adds no authentication or authorization layer;
keep the service on a trusted local interface.

Invalid request/schema input returns `422`; missing workflow or execution IDs
return `404`; invalid execution transitions return `409`; request bodies above
1 MiB return `413`. Error responses use stable codes and omit raw Python
exception messages. The API adds no authentication or authorization layer;
keep the service on a trusted local interface.

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

No real LLM, filesystem, shell, or internet integration is invoked. Direct
engine calls still keep their own state in memory; the Day 12 API adapter
described above persists API-driven execution snapshots and events. This does
not add parallelism, retries, worker infrastructure, or restart recovery.
Tool execution is synchronous; elapsed-time limits are checked after a handler
returns and cannot interrupt a stuck handler. The current tool contract has no
risk-classification or approval/resume workflow, so it enforces registration,
capability, schema, and size policy but does not claim approval gating for side
effects.

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

Terminal snapshots are kept in a bounded in-memory history.
`get_execution(id)` returns a detached snapshot or raises
`ExecutionNotFoundError`; `list_executions(limit=...)` returns recent terminal
executions newest first. Returned snapshots cannot mutate stored history.
This history, active engine objects, and cancellation requests are process-local
and are lost on restart. The Day 12 API separately persists and reconstructs
execution snapshots; it does not rehydrate in-memory engine objects. There are
no retries, worker coordination, or automatic restart recovery.

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
