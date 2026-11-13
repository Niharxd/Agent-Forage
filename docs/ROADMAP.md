# AgentForge Roadmap

The roadmap is milestone-based rather than calendar-based. Each milestone should be accepted before expanding scope. The first implementation milestone is deliberately narrower than the complete product goal.

## Day 2 implementation plan — first vertical slice

**Goal:** prove the safety-critical path with a mock provider and no real external side effects.

1. Establish the Python project structure and dependency/configuration baseline for FastAPI, Pydantic, SQLAlchemy 2.x, Alembic, and pytest; add environment-variable configuration and a placeholder-only `.env.example`.
2. Define versioned execution, plan, step, attempt, approval, and result schemas. Implement DAG/allowlist/limit validation and unit tests for invalid plans.
3. Define provider and tool interfaces plus deterministic mock implementations. Do not add a real LLM integration or shell/exec capability.
4. Implement the smallest engine path: submit → plan → inspect → explicit start → sequential mock steps → reviewer → persisted terminal report. Persist every transition and attempt.
5. Add a no-side-effect approval-required mock tool and verify that it is not called before explicit approval and is never called after rejection.
6. Add a minimal React/Vite/TypeScript UI only if the backend vertical slice and tests are stable; show plan/state/history before polishing graph interactions.
7. Add focused CI tests and local Docker development instructions. Stop after the acceptance criteria for this slice pass; do not add multi-user auth, real integrations, parallel workers, or deployment automation beyond the agreed local path.

**Day 2 exit criteria:** mock end-to-end execution is durable across API restart; unsafe plans are rejected; approval tests prove zero premature invocation; retry/timeout behavior is bounded; focused backend and frontend tests pass without network access or paid credentials.

## Day 15 interpretation — first M3 integration slice

The roadmap defines milestones, not a calendar-day schedule, so it does not
define a separate Day 15. After Day 14's dependency-graph view, the next
logical milestone is M3, the first real provider and read-only integration.
For this implementation, the operator selected:

- OpenAI Chat Completions as an opt-in provider for the Planner role. Mock mode
  remains the default.
- A fixed-endpoint, read-only English Wikipedia search tool for Researcher
  tasks. It accepts a query rather than an arbitrary URL and runs only after
  explicit workflow start.

This is an initial M3 slice, not the completion of every M3 operational
requirement. It adds environment-backed credentials and bounded adapter
contracts, with no arbitrary code, shell execution, writes, or general-purpose
network access.

## Day 16 — Planner integration

`WorkflowOrchestrator.prepare()` now uses the Planner already registered by the
`WorkflowEngine`, so its mock/OpenAI choice comes from the existing
`PROVIDER_MODE` setting. Mock mode remains the default. Provider-backed
preparation and failure handling are tested with mocked HTTP responses; no
provider retries or new network capabilities are added.

## Day 17 — Durable Planner task intake

The workflow API now accepts a bounded natural-language task, plans it through
the engine-configured Planner, and persists the validated workflow together
with its pending execution in one database transaction. The response includes
the workflow definition for operator review and the existing safe execution
projection. Planning never starts execution; operators still use the existing
explicit start endpoint. No schema migration or new provider/network behavior
is introduced. The dashboard remains fixture-driven and is not connected in
this increment. Planner objectives longer than the existing workflow
description limit are visibly abbreviated; the original task and task
instructions retain their full independently bounded content.

## Milestones

### M0 — Specification and repository baseline

- Confirm product boundaries and initial decisions.
- Inspect the repository; preserve existing conventions and code.
- Agree on authentication, data retention, first provider/tool, and deployment assumptions.
- **Exit:** docs reviewed; open questions have owners or explicit defaults.

### M1 — Safe backend vertical slice

- Implement schemas, persistence, planning/execution interfaces, mock provider/tool, bounded sequential engine, approval state, and API.
- Validate state transitions, restart behavior, and failure handling.
- **Exit:** Day 2 criteria pass; no generated code execution or real side effects.

### M2 — Usable operator dashboard

- Add plan visualization, execution history, step log/error views, and approval UI.
- Add accessibility and API error/loading states.
- **Exit:** UI acceptance criteria pass against mock executions.

### M3 — First real provider and read-only integration

- Select provider and one low-risk read-only tool.
- Add secret configuration, redaction, provider-specific timeout/rate-limit handling, and adapter contract tests.
- **Exit:** provider/tool failures are observable; credentials are absent from logs, responses, and persisted records.

### M4 — Hardened private deployment

- Resolve authentication/authorization, transport security, database backups, retention, migration/rollback, monitoring, and recovery operations.
- Add container image/build and deployment documentation for the selected target.
- **Exit:** security and operational review accepted for the defined private deployment boundary.

### M5 — Expanded capabilities (only after measurement)

- Consider additional tools, controlled parallelism, richer retry classes, and multi-user access based on demonstrated demand and threat review.
- **Exit:** each capability has explicit policy, limits, recovery semantics, tests, and an owner.

## Delivery guardrails

- Do not add a tool without a typed schema, capability allowlist, risk assessment, and failure/idempotency policy.
- Do not add concurrency before claim/recovery behavior is tested with multiple workers.
- Do not call a deployment production-ready until authentication, authorization, secrets, data handling, recovery, and monitoring are verified for its threat boundary.
- Keep core workflow tests provider-independent; mock mode must remain available.
