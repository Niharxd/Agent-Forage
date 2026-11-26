import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Layers3,
  ListChecks,
  Plus,
  RefreshCw,
  Workflow as WorkflowIcon,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  listExecutions,
  listPendingApprovals,
  listWorkflows,
  type Execution,
  type PendingApproval,
  type WorkflowRecord,
} from "../api/executions";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";

type DashboardErrorKey = "workflows" | "executions" | "completed" | "failed" | "approvals";
type DashboardErrors = Partial<Record<DashboardErrorKey, string>>;

const statusDetails = {
  pending: { label: "Pending", tone: "blue" as const },
  running: { label: "Running", tone: "violet" as const },
  waiting_approval: { label: "Awaiting approval", tone: "violet" as const },
  completed: { label: "Completed", tone: "green" as const },
  failed: { label: "Failed", tone: "red" as const },
  cancelled: { label: "Cancelled", tone: "neutral" as const },
};

const metricIconColors = {
  violet: "text-[var(--accent)]",
  blue: "text-[var(--info)]",
  green: "text-[var(--success)]",
  red: "text-[var(--error)]",
};

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Time unavailable" : date.toLocaleString();
}

function formatDuration(execution: Execution): string | null {
  if (!execution.started_at) return null;
  if (!execution.completed_at) return "In progress";
  const seconds = Math.max(
    0,
    Math.floor((Date.parse(execution.completed_at) - Date.parse(execution.started_at)) / 1000),
  );
  if (!Number.isFinite(seconds)) return null;
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return seconds < 3600
    ? `${minutes}m ${seconds % 60}s`
    : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function SectionError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="m-4 rounded-lg border border-[var(--error)]/30 bg-[var(--error)]/5 p-4">
      <p className="text-sm text-[var(--error)]">{message}</p>
      <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

function LoadingRows({ label }: { label: string }) {
  return (
    <div className="space-y-3 p-5" role="status" aria-label={label}>
      {[0, 1, 2].map((item) => (
        <div key={item} className="h-14 animate-pulse rounded-lg bg-[var(--surface-alt)]" />
      ))}
    </div>
  );
}

export default function UserDashboardPage() {
  const [workflows, setWorkflows] = useState<WorkflowRecord[] | null>(null);
  const [workflowTotal, setWorkflowTotal] = useState<number | null>(null);
  const [executions, setExecutions] = useState<Execution[] | null>(null);
  const [executionTotal, setExecutionTotal] = useState<number | null>(null);
  const [completedTotal, setCompletedTotal] = useState<number | null>(null);
  const [failedTotal, setFailedTotal] = useState<number | null>(null);
  const [approvals, setApprovals] = useState<PendingApproval[] | null>(null);
  const [approvalTotal, setApprovalTotal] = useState<number | null>(null);
  const [errors, setErrors] = useState<DashboardErrors>({});
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setErrors({});

    Promise.allSettled([
      listWorkflows(controller.signal, { limit: 5, sort: "updated" }),
      listExecutions({ limit: 8, offset: 0, status: undefined, search: "" }, controller.signal),
      listExecutions({ limit: 1, offset: 0, status: "completed", search: "" }, controller.signal),
      listExecutions({ limit: 1, offset: 0, status: "failed", search: "" }, controller.signal),
      listPendingApprovals({ limit: 5, offset: 0 }, controller.signal),
    ]).then(([workflowResult, executionResult, completedResult, failedResult, approvalResult]) => {
      if (controller.signal.aborted) return;
      const nextErrors: DashboardErrors = {};
      if (workflowResult.status === "fulfilled") {
        setWorkflows(workflowResult.value.items);
        setWorkflowTotal(workflowResult.value.total);
      } else {
        nextErrors.workflows = workflowResult.reason instanceof Error
          ? workflowResult.reason.message
          : "Workflow data could not be loaded.";
      }
      if (executionResult.status === "fulfilled") {
        setExecutions(executionResult.value.items);
        setExecutionTotal(executionResult.value.total);
      } else {
        nextErrors.executions = executionResult.reason instanceof Error
          ? executionResult.reason.message
          : "Execution data could not be loaded.";
      }
      if (completedResult.status === "fulfilled") {
        setCompletedTotal(completedResult.value.total);
      } else {
        nextErrors.completed = completedResult.reason instanceof Error
          ? completedResult.reason.message
          : "Successful execution totals could not be loaded.";
      }
      if (failedResult.status === "fulfilled") {
        setFailedTotal(failedResult.value.total);
      } else {
        nextErrors.failed = failedResult.reason instanceof Error
          ? failedResult.reason.message
          : "Failed execution totals could not be loaded.";
      }
      if (approvalResult.status === "fulfilled") {
        setApprovals(approvalResult.value.items);
        setApprovalTotal(approvalResult.value.total);
      } else {
        nextErrors.approvals = approvalResult.reason instanceof Error
          ? approvalResult.reason.message
          : "Pending approvals could not be loaded.";
      }
      setErrors(nextErrors);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });

    return () => controller.abort();
  }, [refresh]);

  const metricCards = [
    { label: "Total workflows", value: workflowTotal, icon: Layers3, tone: "violet", error: errors.workflows, showError: false },
    { label: "Total executions", value: executionTotal, icon: Activity, tone: "blue", error: errors.executions, showError: false },
    { label: "Successful executions", value: completedTotal, icon: CheckCircle2, tone: "green", error: errors.completed, showError: true },
    { label: "Failed executions", value: failedTotal, icon: XCircle, tone: "red", error: errors.failed, showError: true },
    { label: "Pending approvals", value: approvalTotal, icon: ListChecks, tone: "violet", error: errors.approvals, showError: false },
  ] as const;

  return (
    <div className="mx-auto max-w-[1440px]">
      <PageHeader
        title="Your workspace"
        description="A clear view of your workflows, execution activity, and items awaiting review."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => setRefresh((value) => value + 1)}
              disabled={loading}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
            <Link to="/workflows#new-workflow">
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                Create workflow
              </Button>
            </Link>
          </>
        }
      />

      <section className="mb-6 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex flex-col justify-between gap-6 p-6 md:p-8 lg:flex-row lg:items-center">
          <div className="max-w-2xl">
            <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[.15em] text-[var(--accent)]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
              Workspace overview
            </div>
            <h2 className="text-2xl font-semibold tracking-tight md:text-[28px]">
              Welcome back. What would you like to work on?
            </h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--secondary)]">
              Prepare a workflow, follow its execution, and keep approvals moving from one place.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Link to="/workflows#new-workflow">
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                Create a workflow
              </Button>
            </Link>
            <Link to="/workflows">
              <Button variant="secondary">
                View workflows
                <ArrowUpRight className="ml-2 h-4 w-4" />
              </Button>
            </Link>
          </div>
        </div>
      </section>

      <section aria-label="Workspace statistics" className="mb-7">
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Workspace at a glance</h2>
            <p className="mt-1 text-xs text-[var(--muted)]">Current totals from your workspace history</p>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {metricCards.map(({ label, value, icon: Icon, tone, error, showError }) => (
            <article
              key={label}
              className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 transition-colors hover:border-[var(--accent)]/40"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-[var(--secondary)]">{label}</span>
                <Icon size={16} className={metricIconColors[tone]} />
              </div>
              <div className="mt-4 text-3xl font-semibold tracking-tight tabular-nums">
                {loading && value === null ? "–" : value === null ? "—" : value.toLocaleString()}
              </div>
              <p
                role={error && showError ? "alert" : undefined}
                title={error}
                className={`mt-1 line-clamp-2 text-[11px] ${error ? "text-[var(--error)]" : "text-[var(--muted)]"}`}
              >
                {error
                  ? showError ? `Unavailable: ${error}` : "Unavailable"
                  : label === "Pending approvals"
                    ? "Awaiting a decision"
                    : "Across your workspace"}
              </p>
            </article>
          ))}
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[1.4fr_.9fr]">
        <section className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold">Recent executions</h2>
              <p className="mt-1 text-xs text-[var(--muted)]">Latest activity in your workspace</p>
            </div>
            <Link to="/executions" className="shrink-0 text-xs font-medium text-[var(--accent)] hover:underline">
              View history <ArrowUpRight className="ml-1 inline" size={13} />
            </Link>
          </div>
          {errors.executions ? (
            <SectionError message={errors.executions} onRetry={() => setRefresh((value) => value + 1)} />
          ) : loading && executions === null ? (
            <LoadingRows label="Loading recent executions" />
          ) : executions?.length === 0 ? (
            <div className="p-5">
              <EmptyState
                title="Your activity will appear here"
                description="Once you prepare and run a workflow, its latest status and timing will show up in this list."
                action={
                  <Link to="/workflows#new-workflow">
                    <Button>
                      <Plus className="mr-2 h-4 w-4" />
                      Prepare a workflow
                    </Button>
                  </Link>
                }
              />
            </div>
          ) : (
            <div className="divide-y divide-[var(--border)]">
              {executions?.map((execution) => {
                const status = statusDetails[execution.status];
                const duration = formatDuration(execution);
                return (
                  <Link
                    key={execution.execution_id}
                    to={`/executions?execution=${encodeURIComponent(execution.execution_id)}`}
                    className="flex flex-col gap-3 px-5 py-4 transition-colors hover:bg-[var(--surface-alt)] sm:flex-row sm:items-center"
                  >
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] text-[var(--accent)]">
                      <WorkflowIcon size={16} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{execution.workflow_name}</span>
                      <span className="mt-1 flex items-center gap-1.5 text-xs text-[var(--muted)]">
                        <Clock3 size={12} />
                        {formatTimestamp(execution.started_at ?? execution.created_at)}
                      </span>
                    </span>
                    {duration && <span className="text-xs text-[var(--secondary)]">{duration}</span>}
                    <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
                  </Link>
                );
              })}
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold">Pending approvals</h2>
              <p className="mt-1 text-xs text-[var(--muted)]">Actions that need a workspace decision</p>
            </div>
            <span className="rounded-full border border-[var(--border)] px-2 py-1 text-[11px] tabular-nums text-[var(--secondary)]">
              {loading && approvalTotal === null ? "–" : approvalTotal ?? "—"}
            </span>
          </div>
          {errors.approvals ? (
            <SectionError message={errors.approvals} onRetry={() => setRefresh((value) => value + 1)} />
          ) : loading && approvals === null ? (
            <LoadingRows label="Loading pending approvals" />
          ) : approvals?.length === 0 ? (
            <div className="p-5">
              <EmptyState
                title="Nothing needs your attention"
                description="When a workflow pauses for approval, its requested action will appear here."
              />
            </div>
          ) : (
            <div className="divide-y divide-[var(--border)]">
              {approvals?.map((approval) => (
                <article key={approval.approval_id} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-medium">{approval.workflow_name}</h3>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--secondary)]">
                        {approval.action_description}
                      </p>
                    </div>
                    <StatusBadge tone="blue">Pending</StatusBadge>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[11px] text-[var(--muted)]">
                      {[approval.task_id && `Task ${approval.task_id}`, approval.tool_id && `Tool ${approval.tool_id}`]
                        .filter(Boolean)
                        .join(" · ") || "Requested action"}
                      {" · "}{formatTimestamp(approval.requested_at)}
                    </span>
                    <Link
                      to={`/executions?execution=${encodeURIComponent(approval.execution_id)}`}
                      className="text-xs font-medium text-[var(--accent)] hover:underline"
                    >
                      Review <ArrowUpRight className="ml-1 inline" size={13} />
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="mt-5 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold">Workflow overview</h2>
            <p className="mt-1 text-xs text-[var(--muted)]">Recently updated definitions</p>
          </div>
          <Link to="/workflows" className="text-xs font-medium text-[var(--accent)] hover:underline">
            All workflows <ArrowUpRight className="ml-1 inline" size={13} />
          </Link>
        </div>
        {errors.workflows ? (
          <SectionError message={errors.workflows} onRetry={() => setRefresh((value) => value + 1)} />
        ) : loading && workflows === null ? (
          <LoadingRows label="Loading workflows" />
        ) : workflows?.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="Start with your first workflow"
              description="Create a workflow from a task description. Your saved definitions will be organized here as they are updated."
              action={
                <Link to="/workflows#new-workflow">
                  <Button>
                    <Plus className="mr-2 h-4 w-4" />
                    Create a workflow
                  </Button>
                </Link>
              }
            />
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {workflows?.map((workflow) => (
              <Link
                key={workflow.id}
                to={`/workflows?workflow=${encodeURIComponent(workflow.id)}`}
                className="flex flex-col gap-2 px-5 py-4 transition-colors hover:bg-[var(--surface-alt)] sm:flex-row sm:items-center"
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] text-[var(--accent)]">
                  <Layers3 size={16} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{workflow.name}</span>
                  <span className="mt-1 block truncate text-xs text-[var(--secondary)]">
                    {workflow.description || "No description"}
                  </span>
                </span>
                <span className="text-xs text-[var(--muted)]">v{workflow.version}</span>
                <span className="text-xs text-[var(--muted)]">
                  Updated {formatTimestamp(workflow.updated_at)}
                </span>
                <StatusBadge tone="neutral">Saved</StatusBadge>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
