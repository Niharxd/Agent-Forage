import { RefreshCw, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { getExecution, listExecutions, type Execution, type ExecutionStatus } from "../api/executions";
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
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function statusTone(status: ExecutionStatus): "blue" | "violet" | "green" | "red" | "neutral" {
  switch (status) {
    case "pending":
      return "blue";
    case "running":
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

function ExecutionDetails({ execution }: { execution: Execution }) {
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

export default function ExecutionsPage() {
  const [searchValue, setSearchValue] = useState("");
  const [statusFilter, setStatusFilter] = useState<ExecutionStatus | "all">("all");
  const [page, setPage] = useState(0);
  const [reloadList, setReloadList] = useState(0);
  const [response, setResponse] = useState<Awaited<ReturnType<typeof listExecutions>> | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);
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
          <ExecutionDetails execution={selectedExecution} />
        ) : null
      ) : null}

      <div className="mt-6 flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--secondary)]">
        <Search className="h-3.5 w-3.5" />
        Search and status filters use the persisted API. Raw task payloads and tool arguments are not rendered here.
      </div>
    </div>
  );
}
