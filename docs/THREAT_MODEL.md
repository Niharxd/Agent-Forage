# AgentForge Threat Model

## Scope and security objective

This model covers task submission, LLM-based planning and role execution, tool policy/approval, persistence, the API, worker, and dashboard. The initial trust boundary is a single operator on a local machine with the API bound to loopback. Private-network exposure requires an agreed authentication mechanism. The MVP is not claimed to be safe for anonymous internet access, multiple mutually untrusted tenants, or high-impact autonomous operations.

**Security objectives:** prevent unauthorized or unintended side effects; constrain agent capabilities; preserve truthful execution history; protect credentials and sensitive task data; and expose failures without representing partial work as success.

## Assets

- Provider credentials, database credentials, and any future tool credentials.
- User task text, plans, prompts, tool arguments/results, and reports.
- Approval decisions and the identity/context of the approver.
- Workflow state, step outputs, attempt history, and audit events.
- Availability and integrity of the API, worker, and PostgreSQL database.

## Trust boundaries and assumptions

- User input, model output, tool output, and content retrieved by tools are untrusted.
- Provider responses may be malformed, adversarially influenced, incomplete, or false.
- The operator is trusted to configure the service and approve displayed actions; the MVP does not provide multi-party approval.
- PostgreSQL and the host are trusted infrastructure. Compromise of the host/database is outside the MVP's primary mitigation boundary.
- Providers receive only task/context required for a call; provider retention and training policies must be evaluated before real user data is sent.
- Network ingress is loopback-only for the initial MVP; TLS is required wherever traffic crosses an untrusted network in later deployments.
- Tool adapters are trusted code but must still validate inputs, enforce least privilege, and avoid logging secrets.

## Threats and mitigations

| Threat | Impact | Required mitigation |
|---|---|---|
| Prompt injection in task/tool-returned content | Planner/agent attempts to ignore policy, disclose data, or request a risky action | Treat prompts as untrusted; keep policy outside prompts; engine validates every plan and call; tool output does not grant capabilities; require approval for sensitive effects. |
| Malicious or malformed generated plan | Hidden dependency, oversized plan, unauthorized tool, or unsafe execution | Strict versioned schema, DAG and bounds validation, role/tool allowlists, explicit user start, deny by default. |
| Unauthorized tool invocation | Data loss, disclosure, or external changes | Only registered adapters; engine-mediated invocation; typed arguments; no shell/exec; risk policy checked at invocation, not only planning. |
| Approval bypass or replay | Sensitive action runs without valid consent or after arguments changed | Persist approval request; bind decision to execution, tool, canonical argument digest, expiry, and approver; single-use decision; revalidate immediately before invocation. |
| Ambiguous timeout/retry duplicates a side effect | Duplicate external operation | Retry only classified transient failures; require idempotency contract/key for side-effect retry; otherwise mark outcome ambiguous and request operator recovery. |
| Credential leakage in prompt, logs, API, or database | Account compromise | Environment/secret-store configuration; never put secrets in prompts or user-visible results; structured redaction; avoid logging headers/credential-bearing arguments; test redaction. |
| Cross-site scripting through task/plan/tool output | Operator session compromise | Render untrusted values as text; sanitize any explicitly supported rich text; use standard React escaping and a restrictive Content Security Policy in deployed UI. |
| API abuse or unauthorized approval | Workflow manipulation or data exposure | Restrict network exposure; implement the agreed authentication before non-local use; authorize every state-changing endpoint; rate/size limits; audit actor. |
| Database tampering or deletion | False history, lost work, unauthorized disclosure | Least-privilege DB account; network isolation; backups and restore tests; append-only audit discipline at application level; encryption/retention policy determined for deployment. |
| Resource exhaustion via large tasks, plans, loops, or slow provider calls | Service degradation/cost escalation | 10,000-character task limit, plan/step limits, one tool request per step, timeouts, retry/active-duration caps, provider budgets/rate limits, and a single worker in the MVP. |
| Worker crash/replay during external action | Concurrent or duplicated side effects; misleading status | Durable execution claim, failed state with recovery-required reason for ambiguity, idempotency rules, transactionally persisted transitions; do not claim exactly-once effects. |
| Dependency or container compromise | Code execution, credential theft, supply-chain risk | Pin/review dependencies and base images, scan in CI, minimal runtime privileges, no Docker socket exposure, controlled image provenance (deployment milestone). |

## Security requirements and checks

1. No workflow field is interpreted as Python, shell, SQL, JavaScript, or another executable program.
2. Unknown tools, invalid arguments, invalid approvals, and unavailable persistence fail closed; they must not fall through to a permissive default.
3. Gated tools have zero invocations until valid approval is committed and rechecked.
4. Tool handlers are explicit callables registered in trusted application code; the runtime does not dynamically import modules or load arbitrary handlers from untrusted inputs.
5. Logs and API responses never include configured credential values; tests use sentinel secrets to verify redaction.
6. State-changing endpoints require the configured operator authorization in any deployment beyond local-only development.
7. Persisted user/model content has documented access, retention, deletion, and provider-sharing rules before handling sensitive production data.
8. Build/runtime containers run as non-root where supported and do not receive host execution privileges.

## Day 9 tool-safety note

The Day 9 tool registry intentionally excludes arbitrary shell execution, filesystem access, network access, code evaluation, and dynamic imports. The single-operator MVP still relies on trustworthy application code for the registered handlers, and hard process-level timeouts are not enforced for arbitrary synchronous Python handlers without operating-system-level isolation. The Safe tool layer therefore enforces deny-by-default registration, explicit agent capabilities, schema validation, and safe failure reporting while leaving full external side-effect isolation to later milestones.

## Residual risks and out of scope

- LLM content can be inaccurate or manipulated despite schema and policy controls.
- Human approval can be careless; approval is not proof that an external action is safe.
- A provider may retain or process submitted content according to its own terms.
- The single-operator MVP does not prevent abuse by a compromised operator account or host.
- Exactly-once behavior for external side effects is not generally achievable; ambiguous outcomes need human resolution.
- Multi-tenant isolation, enterprise identity, advanced audit integrity, and public-internet threat coverage are deferred and must be designed before those deployment modes.

## Security review triggers

Revisit this model before adding any real side-effect tool, browser automation, multi-user access, public exposure, file uploads, secrets retrieval, parallel workers, or a provider that receives sensitive data. Each trigger requires a concrete abuse-case review and tests for the changed boundary.
