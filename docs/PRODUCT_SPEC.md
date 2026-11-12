# AgentForge Product Specification

## Purpose

AgentForge turns a user's natural-language task into a validated, inspectable workflow, executes that workflow through specialized agents and explicitly registered tools, records its progress, validates the result, and returns a report.

The initial release is a single-operator, self-hosted MVP for bounded workflows. It is not a general-purpose autonomous computer-use agent, a code-generation runtime, or a multi-tenant SaaS product.

## Users and primary use case

**Primary user:** a technically capable operator who submits a task, inspects the proposed plan, approves gated actions, and reviews the execution report.

**Primary flow:** submit task → review structured plan → start execution → respond to approval requests → inspect steps and final report.

## Scope

### MVP

- Natural-language task submission and persisted execution history.
- Planner-generated workflows represented as validated JSON data, never executable code.
- Planner, Researcher, Analyst, and Reviewer roles, with responsibilities constrained by the workflow engine.
- A deterministic, bounded, sequential workflow engine.
- A registry of explicitly configured tools with typed inputs, risk classification, and policy checks.
- Approval gates for sensitive or externally visible tool actions.
- Bounded retries and timeouts, explicit failure states, and step-level logs.
- PostgreSQL persistence, a React dashboard, and a mock LLM provider usable without paid credentials.
- An opt-in OpenAI Planner adapter and a capability-gated, read-only English Wikipedia search tool; mock mode remains the default.
- Automated backend and frontend tests, local Docker-based development, and CI.

### Not in the MVP

- Arbitrary shell commands, unrestricted code execution, or agent-selected tools outside the registry.
- Unattended execution of sensitive actions, general browser/computer control, or self-modifying workflows.
- Multi-tenant isolation, enterprise SSO/RBAC, billing, high availability, or a hosted service.
- Parallel task execution, distributed scheduling, and exactly-once execution guarantees.
- A promise that LLM output is reproducible. Determinism applies to orchestration decisions, not model-generated content.

## Functional requirements

| ID | Requirement |
|---|---|
| FR-01 | A user can submit a non-empty task of at most 10,000 characters. The API returns an execution identifier and a persisted initial state. |
| FR-02 | The Planner returns a structured plan with named steps, assigned roles, declared dependencies, bounded inputs, and any requested tool capabilities. Invalid plans are rejected before execution. |
| FR-03 | Plan validation rejects unknown roles/tools, duplicate step IDs, missing dependencies, cycles, invalid references, and plans beyond configured limits. |
| FR-04 | A user can inspect and explicitly start a validated plan. Planning does not itself execute tools or cause external side effects. |
| FR-05 | The engine executes ready steps sequentially in a stable order, supplies only declared dependency outputs, and records each attempt and state transition. |
| FR-06 | The Researcher and Analyst produce task-scoped outputs; the Reviewer evaluates the final result against the request and available evidence. Agent roles do not bypass engine or tool policy. |
| FR-07 | Only registered tools with validated schemas can be called. Each step may request at most one tool invocation; additional work requires another declared step. Tool policy classifies actions as read-only or approval-required and denies anything not explicitly allowed. |
| FR-08 | Approval-required actions pause before invocation. The user can approve or reject the specific action; an approval is bound to the displayed tool and argument digest and cannot authorize changed arguments. |
| FR-09 | Retry count, per-attempt timeout, and total execution duration are bounded. Permanent failures are not retried; external side effects are not retried unless the tool has an explicit idempotency contract. |
| FR-10 | The user can inspect execution status, step outputs/logs, approval requests, errors, and the final report after refresh or service restart. |
| FR-11 | A mock provider implements the same provider interface as a configured LLM provider and supports deterministic test scenarios without network access or credentials. |
| FR-12 | The dashboard visualizes the dependency graph and execution states and presents step logs and approval requests. It does not expose provider secrets. |
| FR-13 | Operators can configure provider credentials and runtime limits through environment/configuration mechanisms; secrets are not committed or stored in workflow records. |
| FR-14 | The service exposes health/readiness information and structured logs sufficient to diagnose planning, execution, persistence, provider, and tool failures. |

## Non-functional requirements

- **Safety:** no arbitrary generated code or shell execution; deny-by-default tool access; approval before sensitive side effects.
- **Boundedness:** initial defaults are at most 25 steps, 2 retries after the first attempt, 60 seconds per agent/tool attempt, 15 minutes of active execution time, and 10,000 characters per task. Human approval wait is excluded from active execution time; an approval request expires after 24 hours. Limits are enforced server-side and may be lowered by operators. Increasing them requires explicit configuration and tests.
- **Reliability:** execution state and step results are committed to PostgreSQL before being reported as durable; a restart must not silently convert an incomplete execution to success.
- **Consistency:** each execution follows validated dependencies and explicit state transitions; retries and approval decisions are visible in history.
- **Performance target:** for a local development deployment, submit/plan/status API operations (excluding provider latency) should have p95 latency below 500 ms with 10 concurrent API clients and 100 stored executions. This is an MVP target to verify, not a production capacity claim.
- **Usability:** a user can identify the current execution state, blocked reason, next required action, and final outcome without reading server logs.
- **Testability:** orchestration and policy tests run against the mock provider and fake tools without network access or paid APIs.
- **Maintainability:** provider, tool, persistence, API, and UI boundaries are explicit; schemas are versioned so saved executions remain interpretable.
- **Security:** credentials are supplied out of band, protected in transit in deployed environments, excluded from logs and persisted user-visible output, and never included in source control.
- **External data:** when OpenAI mode is enabled, only the Planner task description is sent to OpenAI; a Wikipedia tool request sends only its bounded query to English Wikipedia. Operators must not submit secrets or sensitive data to either integration.

## Workflow lifecycle

1. **Submit:** validate task bounds, create an execution record in `submitted`.
2. **Plan:** Planner proposes structured data. Validate schema, dependency DAG, role/tool allowlists, and limits. Persist the plan and planning outcome.
3. **Review plan:** show the plan to the user. No task execution or tool call occurs until the user starts it.
4. **Queue and execute:** explicit user start persists `queued`. The worker claims it and transitions to `running` before selecting the next ready step by stable plan order or invoking its agent/provider.
5. **Gate:** if a tool action requires approval, persist the exact request and transition to `waiting_approval` before invocation. Rejection or expiry fails the execution without invoking the action; approval resumes only the approved action. Approval waits do not consume the active execution budget.
6. **Record and continue:** persist attempt result, timing, and state. Continue with the next dependency-ready step, or apply the bounded retry policy.
7. **Review result:** after all planned steps succeed, invoke the Reviewer and persist its assessment. Reviewer rejection produces a failed execution, not a success-shaped report.
8. **Finish:** persist `succeeded`, `failed`, or `cancelled` and a user-facing report. Terminal states do not transition back to active states.

Planning failure ends in `failed` with a planning error and no runnable plan. A process restart may leave an execution interrupted; recovery policy must mark/reattempt only safe work and must not infer that a side effect did not happen. An ambiguous non-idempotent outcome is represented as `failed` with a recovery-required reason for operator inspection.

## Acceptance criteria

1. Submitting a valid task with the mock provider creates a durable execution, validated DAG, and inspectable plan; it makes zero tool calls before an explicit start.
2. A plan with a cycle, missing dependency, duplicate ID, unknown role/tool, or more than 25 steps is rejected with a specific validation error and is not executable.
3. For a fixed plan and fixed mock outputs, execution chooses steps in the same stable order, never starts a step before its dependencies succeed, and records every attempt and transition.
4. An approval-required tool is not invoked before approval; rejection results in zero invocation; changing any approved argument invalidates that approval.
5. A transient failure is retried no more than twice after its first attempt. A permanent failure is not retried. A non-idempotent external action is not automatically repeated after an ambiguous timeout.
6. An agent/tool attempt exceeding 60 seconds is stopped or marked timed out, and active execution cannot exceed 15 minutes; time spent awaiting approval is excluded and approval expires after 24 hours.
7. After an application restart, persisted terminal history and completed step records remain queryable; an interrupted execution is visibly recoverable or failed, never falsely reported as successful.
8. A step requesting more than one tool invocation is rejected; additional tool actions require separate declared steps.
9. The dashboard renders the DAG, per-step state, logs/errors, pending approvals, and final report for a mock-provider execution.
10. Backend tests and frontend tests pass in CI without external LLM credentials or network calls; the mock-provider test suite verifies that no secret values appear in logs or API responses.

## Assumptions and constraints

- The first deployment is for one trusted operator on a local machine. Private-network exposure requires an agreed authentication mechanism.
- A real LLM provider is an optional adapter; mock mode is the default for development and tests.
- The database is the durable source of truth. In-memory state is not authoritative.
- LLM output, tool output, and user task text are untrusted input and require schema validation, policy checks, and safe rendering.
- Provider calls can fail, time out, return malformed data, or produce incorrect content. Human review remains necessary for consequential outcomes.
