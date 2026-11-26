import { AlertTriangle, CheckCircle2, RefreshCw, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { cancelExecution, getExecution, listApprovals, listExecutions, reviewApproval, startExecution, type Approval, type Execution, type ExecutionStatus } from "../api/executions";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { PageHeader } from "../components/PageHeader";
import { SearchInput } from "../components/SearchInput";
import { StatusBadge } from "../components/StatusBadge";
import { DataTable } from "../components/DataTable";
import { Dropdown } from "../components/Dropdown";
import { WorkflowPlanGraph } from "../components/WorkflowPlanGraph";

const PAGE_SIZE = 25;

const statusLabels: Record<ExecutionStatus, string> = {
  pending: "Pending",
  running: "Running",
  waiting_approval: "Awaiting approval",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function statusTone(status: ExecutionStatus): "blue" | "violet" | "green" | "red" | "neutral" {
  switch (status) {
    case "pending":
      return "blue";
    case "running":
    case "waiting_approval":
      return "violet";
    case "completed":
      return "green";
    case "failed":
      return "red";
    case "cancelled":
      return "neutral";
  }
}

function isExecutionStatus(value: string): value is ExecutionStatus {
  return ["pending", "running", "completed", "failed", "cancelled"].includes(value);
}

function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt) {
    return "—";
  }
  if (!completedAt) {
    return "In progress";
  }
  const durationSeconds = Math.max(
    0,
    Math.floor((Date.parse(completedAt) - Date.parse(startedAt)) / 1000),
  );
  const hours = Math.floor(durationSeconds / 3600);
  const minutes = Math.floor((durationSeconds % 3600) / 60);
  const seconds = durationSeconds % 60;
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Not started";
  }
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Unavailable" : date.toLocaleString();
}

function ExecutionDetails({ execution, onChanged, canDecideApprovals }: {
  execution: Execution;
  onChanged: () => void;
  canDecideApprovals: boolean;
}) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [approvalReload, setApprovalReload] = useState(0);
  const [reviewedMessage, setReviewedMessage] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    listApprovals(execution.execution_id, controller.signal).then((items) => { if (!controller.signal.aborted) { if (Array.isArray(items)) setApprovals(items); else setApprovalError("The server returned an invalid approval response."); } }).catch((error: unknown) => { if (!controller.signal.aborted) setApprovalError(error instanceof Error ? error.message : "Approval status is unavailable."); });
    return () => controller.abort();
  }, [execution.execution_id, approvalReload]);
  async function decide(approval: Approval, decision: "approve" | "reject") {
    if (acting || approval.status !== "pending") return;
    const prompt = decision === "approve" ? "Approve this action and allow the execution to resume?" : "Reject this action and fail the waiting task?";
    if (!window.confirm(prompt)) return;
    setActing(true); setActionError(null); setReviewedMessage(null);
    try {
      await reviewApproval(execution.execution_id, approval.approval_id, decision);
      setReviewedMessage(decision === "approve" ? "Approval recorded." : "Rejection recorded.");
      setApprovalReload((value) => value + 1);
      onChanged();
    } catch (error) { setActionError(error instanceof Error ? error.message : "Approval decision failed."); }
    finally { setActing(false); }
  }
  async function runAction(action: "start" | "cancel") {
    if (acting) return;
    setActing(true); setActionError(null);
    try { if (action === "start") await startExecution(execution.execution_id); else await cancelExecution(execution.execution_id); onChanged(); }
    catch (error) { setActionError(error instanceof Error ? error.message : "Execution action failed."); }
    finally { setActing(false); }
  }
  const taskIds = [
    ...execution.execution_order,
    ...Object.keys(execution.task_results).filter((taskId) => !execution.execution_order.includes(taskId)),
  ];

  return (
    <section
      aria-label={`Execution details for ${execution.execution_id}`}
      className="mt-6 space-y-5 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text)]">{execution.workflow_name}</h2>
          <p className="mt-1 break-all text-xs text-[var(--muted)]">{execution.execution_id}</p>
        </div>
        <StatusBadge tone={statusTone(execution.status)}>{statusLabels[execution.status]}</StatusBadge>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {execution.status === "pending" && <Button onClick={() => void runAction("start")} disabled={acting}>{acting ? "Starting…" : "Start execution"}</Button>}
        {(execution.status === "pending" || execution.status === "running" || execution.status === "waiting_approval") && <Button variant="secondary" onClick={() => void runAction("cancel")} disabled={acting}>{acting ? "Updating…" : "Cancel execution"}</Button>}
        {actionError && <span role="alert" className="text-xs text-[var(--error)]">{actionError}</span>}
      </div>

      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-alt)] p-4">
        <div className="mb-3 flex items-center gap-2"><AlertTriangle size={15} className="text-amber-300"/><h3 className="text-sm font-semibold">Approvals</h3><span className="ml-auto rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--muted)]">{approvals.filter((item) => item.status === "pending").length} pending</span></div>
        {approvals.map((approval) => <div key={approval.approval_id} className="border-t border-[var(--border)] py-3 first:border-0"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm text-[var(--text)]">{approval.action_description}</p><StatusBadge tone={approval.status === "pending" ? "blue" : approval.status === "approved" ? "green" : "neutral"}>{approval.status}</StatusBadge></div><p className="mt-1 break-all text-[10px] text-[var(--muted)]">Approval {approval.approval_id} · Execution {approval.execution_id} · Tool {approval.tool_id ?? "unavailable"}</p><p className="mt-1 text-xs text-[var(--secondary)]">Task {approval.task_id ?? "unassigned"} · Requested {formatTimestamp(approval.requested_at)}{approval.reviewed_at ? ` · Reviewed ${formatTimestamp(approval.reviewed_at)}` : ""}</p>{approval.status === "pending" && canDecideApprovals && <div className="mt-3 flex gap-2"><Button onClick={() => void decide(approval, "approve")} disabled={acting}>{acting ? "Saving…" : "Approve"}</Button><Button variant="secondary" onClick={() => void decide(approval, "reject")} disabled={acting}>{acting ? "Saving…" : "Reject"}</Button></div>}</div>)}
        {approvals.some((approval) => approval.status === "pending") && !canDecideApprovals && <p className="mt-3 text-xs text-[var(--muted)]">Only workspace owners and admins can decide pending approvals.</p>}
        {actionError && <p role="alert" className="mt-2 text-xs text-[var(--error)]">{actionError}</p>}
        {reviewedMessage && <p role="status" className="mt-2 text-xs text-[var(--success)]">{reviewedMessage}</p>}
        {!approvals.length && !approvalError && <p className="text-xs text-[var(--muted)]"><CheckCircle2 className="mr-1 inline" size={13}/>No approval requests for this execution.</p>}
        {approvalError && <p role="status" className="text-xs text-[var(--muted)]">Approval list unavailable: {approvalError}</p>}
      </div>

      {execution.workflow_plan ? (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-[var(--text)]">Workflow plan</h3>
          <p className="mb-3 text-xs text-[var(--secondary)]">
            Dependency graph and task states. Task inputs and tool arguments are not displayed.
          </p>
          {execution.workflow_plan.length > 0 ? (
            <WorkflowPlanGraph tasks={execution.workflow_plan} />
          ) : (
            <p className="text-sm text-[var(--secondary)]">No plan details are available.</p>
          )}
        </div>
      ) : null}

      <div>
        <h3 className="mb-3 text-sm font-semibold text-[var(--text)]">Tasks</h3>
        {taskIds.length === 0 ? (
          <p className="text-sm text-[var(--secondary)]">No task details are available.</p>
        ) : (
          <div className="space-y-3">
            {taskIds.map((taskId) => {
              const task = execution.task_results[taskId];
              return (
                <article key={taskId} className="rounded-xl border border-[var(--border)] bg-[var(--surface-alt)] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="font-medium text-[var(--text)]">{task.task_id}</h4>
                    <StatusBadge tone={task.status === "completed" ? "green" : task.status === "failed" ? "red" : task.status === "running" ? "violet" : "neutral"}>
                      {task.status}
                    </StatusBadge>
                  </div>
                  <p className="mt-1 text-xs text-[var(--secondary)]">
                    {task.agent_type} · Started {formatTimestamp(task.started_at)} · Completed{" "}
                    {formatTimestamp(task.completed_at)}
                  </p>
                  {task.error ? (
                    <p role="alert" className="mt-3 text-sm text-[var(--error)]">
                      {task.error.message}
                    </p>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold text-[var(--text)]">Execution events</h3>
        {execution.events.length === 0 ? (
          <p className="text-sm text-[var(--secondary)]">No events are available.</p>
        ) : (
          <ol className="space-y-2">
            {execution.events.map((event, index) => (
              <li
                key={`${event.event_type}-${event.timestamp}-${index}`}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-[var(--text)]">
                  <span>{event.event_type.replaceAll("_", " ")}</span>
                  <time className="text-xs text-[var(--secondary)]" dateTime={event.timestamp}>
                    {formatTimestamp(event.timestamp)}
                  </time>
                </div>
                {event.task_id ? <p className="mt-1 text-xs text-[var(--secondary)]">Task: {event.task_id}</p> : null}
                {event.reason ? <p className="mt-1 text-xs text-[var(--secondary)]">{event.reason}</p> : null}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

export default function ExecutionsPage({ canDecideApprovals = true }: { canDecideApprovals?: boolean }) {
  const [searchValue, setSearchValue] = useState("");
  const [statusFilter, setStatusFilter] = useState<ExecutionStatus | "all">("all");
  const [page, setPage] = useState(0);
  const [reloadList, setReloadList] = useState(0);
  const [response, setResponse] = useState<Awaited<ReturnType<typeof listExecutions>> | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("execution"),
  );
  const [selectedExecution, setSelectedExecution] = useState<Execution | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailReload, setDetailReload] = useState(0);
  const [isDetailLoading, setIsDetailLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let recoveringPage = false;
    setIsLoading(true);
    setListError(null);
    listExecutions(
      {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        status: statusFilter === "all" ? undefined : statusFilter,
        search: searchValue,
      },
      controller.signal,
    )
      .then((result) => {
        if (controller.signal.aborted) {
          return;
        }
        if (result.items.length === 0 && (result.total === 0 || page > 0)) {
          if (page > 0) {
            recoveringPage = true;
            setPage(0);
            return;
          }
          if (result.total > 0) {
            setListError("The server reported executions but returned an empty page. Retry to try again.");
            return;
          }
        }
        setResponse(result);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setListError(error instanceof Error ? error.message : "Execution history could not be loaded.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && !recoveringPage) {
          setIsLoading(false);
        }
      });

    return () => controller.abort();
  }, [page, reloadList, searchValue, statusFilter]);

  useEffect(() => {
    if (!selectedExecutionId) {
      setSelectedExecution(null);
      setDetailError(null);
      setIsDetailLoading(false);
      return undefined;
    }

    const controller = new AbortController();
    setIsDetailLoading(true);
    setDetailError(null);
    getExecution(selectedExecutionId, controller.signal)
      .then((execution) => {
        if (!controller.signal.aborted) {
          setSelectedExecution(execution);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setDetailError(error instanceof Error ? error.message : "Execution details could not be loaded.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsDetailLoading(false);
        }
      });

    return () => controller.abort();
  }, [selectedExecutionId, detailReload]);

  const executions = response?.items ?? [];
  const total = response?.total ?? 0;
  const offset = page * PAGE_SIZE;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);

  const rows = executions.map((execution) => ({
    "Execution ID": (
      <button
        type="button"
        aria-expanded={selectedExecutionId === execution.execution_id}
        aria-label={`View execution ${execution.execution_id}`}
        onClick={() =>
          setSelectedExecutionId((current) =>
            current === execution.execution_id ? null : execution.execution_id,
          )
        }
        className="break-all text-left font-medium text-[var(--accent)] hover:underline"
      >
        {execution.execution_id}
      </button>
    ),
    "Workflow name": <span className="text-[var(--secondary)]">{execution.workflow_name}</span>,
    Status: <StatusBadge tone={statusTone(execution.status)}>{statusLabels[execution.status]}</StatusBadge>,
    Created: <span className="text-[var(--secondary)]">{formatTimestamp(execution.created_at)}</span>,
    Duration: (
      <span className="text-[var(--secondary)]">
        {formatDuration(execution.started_at, execution.completed_at)}
      </span>
    ),
  }));

  function updateSearch(value: string) {
    setSearchValue(value);
    setPage(0);
    setSelectedExecutionId(null);
  }

  function updateStatus(value: string) {
    setStatusFilter(value === "all" || isExecutionStatus(value) ? value : "all");
    setPage(0);
    setSelectedExecutionId(null);
  }

  const hasFilters = searchValue.trim().length > 0 || statusFilter !== "all";

  return (
    <div>
      <PageHeader
        title="Executions"
        description="Browse persisted execution history and inspect task results and lifecycle events."
        actions={
          <Button
            variant="secondary"
            onClick={() => setReloadList((current) => current + 1)}
            disabled={isLoading}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        }
      />

      <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 md:flex-row md:items-end">
        <div className="flex-1">
          <SearchInput value={searchValue} onChange={updateSearch} ariaLabel="Search executions" placeholder="Filter executions" />
        </div>
        <div className="w-full md:max-w-[200px]">
          <Dropdown
            label="Status"
            value={statusFilter}
            options={[
              { value: "all", label: "All statuses" },
              { value: "pending", label: "Pending" },
              { value: "running", label: "Running" },
              { value: "waiting_approval", label: "Awaiting approval" },
              { value: "completed", label: "Completed" },
              { value: "failed", label: "Failed" },
              { value: "cancelled", label: "Cancelled" },
            ]}
            onChange={updateStatus}
          />
        </div>
      </div>

      {isLoading ? (
        <LoadingState label="Loading execution history" />
      ) : listError ? (
        <div role="alert" className="rounded-2xl border border-[var(--error)] bg-[var(--surface)] p-5 text-sm text-[var(--error)]">
          <p>{listError}</p>
          <Button variant="secondary" className="mt-3" onClick={() => setReloadList((current) => current + 1)}>
            Retry
          </Button>
        </div>
      ) : executions.length === 0 ? (
        <EmptyState
          title={hasFilters ? "No execution history matches the current filters" : "No executions yet"}
          description={hasFilters ? "Try a different search or status." : "Persisted executions will appear here when workflows are run."}
        />
      ) : (
        <>
          <DataTable columns={["Execution ID", "Workflow name", "Status", "Created", "Duration"]} rows={rows} />
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-[var(--secondary)]">
            <span>
              Showing {pageStart}–{pageEnd} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={page === 0 || isLoading}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={pageEnd >= total || isLoading}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}

      {selectedExecutionId ? (
        isDetailLoading ? (
          <div className="mt-6">
            <LoadingState label="Loading execution details" />
          </div>
        ) : detailError ? (
          <div role="alert" className="mt-6 rounded-2xl border border-[var(--error)] bg-[var(--surface)] p-5 text-sm text-[var(--error)]">
            <p>{detailError}</p>
            <Button
              variant="secondary"
              className="mt-3"
              onClick={() => setDetailReload((current) => current + 1)}
            >
              Retry
            </Button>
          </div>
        ) : selectedExecution ? (
          <ExecutionDetails execution={selectedExecution} canDecideApprovals={canDecideApprovals} onChanged={() => { setDetailReload((value) => value + 1); setReloadList((value) => value + 1); }} />
        ) : null
      ) : null}

      <div className="mt-6 flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--secondary)]">
        <Search className="h-3.5 w-3.5" />
        Search and status filters use the persisted API. Raw task payloads and tool arguments are not rendered here.
      </div>
    </div>
  );
}
