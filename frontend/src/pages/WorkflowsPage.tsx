import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Edit3,
  GitBranch,
  Play,
  Plus,
  Search,
  Workflow,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  archiveWorkflow,
  createPlannedWorkflow,
  getWorkflow,
  listExecutions,
  listWorkflows,
  restoreWorkflow,
  updateWorkflowMetadata,
  type Execution,
  type PrepareResponse,
  type WorkflowRecord,
} from "../api/executions";
import { Button } from "../components/Button";
import { Dropdown } from "../components/Dropdown";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { WorkflowPlanGraph } from "../components/WorkflowPlanGraph";

const PAGE_SIZE = 25;

function formatDate(value: string | null | undefined): string {
  if (!value) return "No executions yet";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "Unavailable" : parsed.toLocaleString();
}

function statusTone(status: Execution["status"]): "blue" | "violet" | "green" | "red" | "neutral" {
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

function WorkflowRegistryPage() {
  const [items, setItems] = useState<WorkflowRecord[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"active" | "archived" | "all">("active");
  const [sort, setSort] = useState<"updated" | "name">("updated");
  const [task, setTask] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [success, setSuccess] = useState<PrepareResponse | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [searchParams] = useSearchParams();
  const selectedWorkflowId = searchParams.get("workflow");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setListError(null);
    listWorkflows(controller.signal, {
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
      search,
      sort,
      status: statusFilter,
    })
      .then((data) => {
        if (!controller.signal.aborted) {
          setItems(data.items);
          setTotal(data.total);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setListError(reason instanceof Error ? reason.message : "Workflow list could not be loaded.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [page, reload, search, sort, statusFilter]);

  useEffect(() => {
    if (!selectedWorkflowId || loading || items.some((workflow) => workflow.id === selectedWorkflowId)) {
      return undefined;
    }
    const controller = new AbortController();
    getWorkflow(selectedWorkflowId, controller.signal)
      .then((workflow) => {
        if (!controller.signal.aborted) {
          setItems((current) =>
            current.some((item) => item.id === workflow.id) ? current : [workflow, ...current],
          );
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setListError(reason instanceof Error ? reason.message : "Workflow could not be opened.");
        }
      });
    return () => controller.abort();
  }, [items, loading, selectedWorkflowId]);

  useEffect(() => {
    if (!selectedWorkflowId || loading || !items.some((workflow) => workflow.id === selectedWorkflowId)) {
      return;
    }
    document.getElementById(`workflow-${selectedWorkflowId}`)?.scrollIntoView?.({
      behavior: "smooth",
      block: "center",
    });
  }, [items, loading, selectedWorkflowId]);

  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || !task.trim()) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await createPlannedWorkflow(task.trim());
      setSuccess(result);
      setTask("");
      setReload((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Workflow preparation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function changeSearch(value: string) {
    setSearch(value);
    setPage(0);
  }

  return (
    <div className="mx-auto max-w-[1440px] min-w-0">
      <PageHeader
        title="Workflows"
        description="Build, organize, and review the plans behind your automated work."
        actions={
          <a href="#new-workflow">
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              New workflow
            </Button>
          </a>
        }
      />

      <div className="mb-6 grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
        <section
          id="new-workflow"
          className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 md:p-6"
        >
          <div className="mb-5 flex items-start gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]">
              <Workflow size={18} />
            </div>
            <div>
              <h2 className="text-sm font-semibold">Prepare a workflow</h2>
              <p className="mt-1 text-xs leading-5 text-[var(--secondary)]">
                Describe the outcome. The Planner saves a validated plan for review without
                starting its tasks.
              </p>
            </div>
          </div>
          <form onSubmit={(event) => void prepare(event)} className="space-y-3">
            <label htmlFor="task-description" className="text-xs font-medium text-[var(--secondary)]">
              Task instructions
            </label>
            <textarea
              id="task-description"
              value={task}
              onChange={(event) => setTask(event.target.value)}
              maxLength={10_000}
              rows={5}
              required
              placeholder="Example: Research the latest public guidance on X and prepare a concise summary with source links."
              className="w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3.5 py-3 text-sm leading-6 text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/20"
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-[11px] text-[var(--muted)]">
                {task.length.toLocaleString()} / 10,000 characters
              </span>
              <Button type="submit" disabled={submitting || !task.trim()}>
                {submitting ? "Preparing plan…" : "Prepare for review"}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </form>
          {error && (
            <div role="alert" className="mt-4 rounded-lg border border-rose-400/30 p-3 text-sm text-[var(--error)]">
              {error}
            </div>
          )}
          {success && (
            <div role="status" className="mt-4 rounded-lg border border-emerald-400/30 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-[var(--success)]">
                <CheckCircle2 size={16} />
                Plan prepared and saved
              </div>
              <p className="mt-1 text-xs text-[var(--secondary)]">
                {success.workflow.name} · {success.execution.workflow_plan?.length ?? 0} tasks ·
                execution is pending and has not started.
              </p>
              <Link
                to={`/workflows/${success.workflow.id}`}
                className="mt-3 inline-flex text-xs font-medium text-[var(--accent)] hover:underline"
              >
                View workflow details <ArrowRight className="ml-1" size={14} />
              </Link>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 md:p-6">
          <div className="text-[11px] font-semibold uppercase tracking-[.14em] text-[var(--accent)]">
            Execution control
          </div>
          <h2 className="mt-3 text-lg font-semibold">Plan first. Start explicitly.</h2>
          <p className="mt-2 max-w-lg text-sm leading-6 text-[var(--secondary)]">
            Preparing a workflow stores the draft with a pending execution. No agent or tool task
            runs until you start it from execution controls.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <StatusBadge tone="blue">Pending review</StatusBadge>
            <StatusBadge tone="violet">Explicit start required</StatusBadge>
          </div>
          <div className="mt-5 rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] p-3 text-xs leading-5 text-[var(--muted)]">
            Submitted task descriptions are persisted by the backend. Do not include credentials or
            information that must not be retained.
          </div>
        </section>
      </div>

      <section className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex flex-col gap-4 border-b border-[var(--border)] p-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-sm font-semibold">Workflow registry</h2>
            <p className="mt-1 text-xs text-[var(--muted)]">
              {total.toLocaleString()} {total === 1 ? "workflow" : "workflows"} in this view
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:flex lg:items-end">
            <label className="relative sm:col-span-2 lg:w-72">
              <span className="sr-only">Search workflows</span>
              <Search
                size={15}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]"
              />
              <input
                aria-label="Search workflows"
                value={search}
                onChange={(event) => changeSearch(event.target.value)}
                placeholder="Search name or description"
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] py-2 pl-9 pr-3 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/20"
              />
            </label>
            <Dropdown
              label="Status"
              value={statusFilter}
              options={[
                { value: "active", label: "Active" },
                { value: "archived", label: "Archived" },
                { value: "all", label: "All statuses" },
              ]}
              onChange={(value) => {
                setStatusFilter(value as "active" | "archived" | "all");
                setPage(0);
              }}
            />
            <Dropdown
              label="Sort by"
              value={sort}
              options={[
                { value: "updated", label: "Recently updated" },
                { value: "name", label: "Name A–Z" },
              ]}
              onChange={(value) => setSort(value as "updated" | "name")}
            />
          </div>
        </div>

        {loading ? (
          <div className="space-y-3 p-5" role="status" aria-label="Loading workflows">
            {[1, 2, 3].map((number) => (
              <div
                key={number}
                className="h-20 animate-pulse rounded-lg bg-[var(--surface-alt)]"
              />
            ))}
          </div>
        ) : listError ? (
          <div className="m-5 rounded-lg border border-[var(--error)]/30 p-4 text-sm">
            <p role="alert" className="text-[var(--error)]">
              {listError}
            </p>
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              onClick={() => setReload((value) => value + 1)}
            >
              Retry
            </Button>
          </div>
        ) : items.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title={search ? "No matching workflows" : statusFilter === "archived" ? "No archived workflows" : "No saved workflows yet"}
              description={
                search
                  ? "Try another workflow name or description."
                  : statusFilter === "archived"
                    ? "Archived workflows will appear here and can be restored."
                    : "Preparing your first task creates a validated workflow definition."
              }
            />
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {items.map((workflow) => (
              <article
                id={`workflow-${workflow.id}`}
                key={workflow.id}
                className={`flex min-w-0 flex-col gap-3 px-5 py-4 transition-colors sm:flex-row sm:items-center ${
                  workflow.id === selectedWorkflowId ? "bg-[var(--accent-soft)]" : "hover:bg-[var(--surface-alt)]/70"
                }`}
              >
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] text-[var(--accent)]">
                  <Workflow size={17} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      to={`/workflows/${encodeURIComponent(workflow.id)}`}
                      className="truncate text-sm font-semibold hover:text-[var(--accent)]"
                    >
                      {workflow.name}
                    </Link>
                    <StatusBadge tone={workflow.status === "archived" ? "neutral" : "green"}>
                      {workflow.status === "archived" ? "Archived" : "Active"}
                    </StatusBadge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--secondary)]">
                    {workflow.description || "No description"}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--muted)]">
                    <span>v{workflow.version}</span>
                    <span>{workflow.workflow_definition.tasks.length} steps</span>
                    <span>{workflow.execution_count ?? 0} executions</span>
                    <span>Updated {formatDate(workflow.updated_at)}</span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                  {workflow.execution_count ? (
                    <span className="hidden items-center gap-1 text-xs text-[var(--muted)] lg:inline-flex">
                      <Clock3 size={13} /> Last run {formatDate(workflow.last_execution_at)}
                    </span>
                  ) : null}
                  <Link
                    to={`/executions?workflow_id=${encodeURIComponent(workflow.id)}`}
                    className="inline-flex h-9 items-center rounded-lg border border-[var(--border)] px-3 text-xs font-medium text-[var(--secondary)] transition-colors hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
                  >
                    History
                  </Link>
                  <Link
                    to={`/workflows/${encodeURIComponent(workflow.id)}`}
                    className="inline-flex h-9 items-center gap-1 rounded-lg bg-[var(--accent-soft)] px-3 text-xs font-semibold text-[var(--accent)] transition-colors hover:bg-[var(--accent)]/20"
                  >
                    Details <ArrowRight size={13} />
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )}
        {!loading && !listError && total > PAGE_SIZE && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] px-5 py-3 text-xs text-[var(--secondary)]">
            <span>
              Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={page === 0}
                onClick={() => setPage((value) => Math.max(0, value - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={(page + 1) * PAGE_SIZE >= total}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function WorkflowDetailPage({
  workflowId,
  canManageWorkflows,
}: {
  workflowId: string;
  canManageWorkflows: boolean;
}) {
  const [workflow, setWorkflow] = useState<WorkflowRecord | null>(null);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    getWorkflow(workflowId, controller.signal)
      .then((record) => {
        if (!controller.signal.aborted) {
          setWorkflow(record);
          setName(record.name);
          setDescription(record.description ?? "");
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(reason instanceof Error ? reason.message : "Workflow could not be loaded.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [reload, workflowId]);

  useEffect(() => {
    if (!workflow) return undefined;
    const controller = new AbortController();
    setHistoryLoading(true);
    setHistoryError(null);
    listExecutions(
      { limit: 5, offset: 0, status: undefined, search: "", workflowId },
      controller.signal,
    )
      .then((result) => {
        if (!controller.signal.aborted) setExecutions(result.items);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setHistoryError(
            reason instanceof Error ? reason.message : "Workflow execution history could not be loaded.",
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setHistoryLoading(false);
      });
    return () => controller.abort();
  }, [workflow, workflowId, reload]);

  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      setActionError("Workflow name cannot be blank.");
      return;
    }
    if (normalizedName.length > 200 || description.length > 2_000) {
      setActionError("Name must be at most 200 characters and description at most 2,000.");
      return;
    }
    setSaving(true);
    setActionError(null);
    setSavedMessage(null);
    try {
      const updated = await updateWorkflowMetadata(workflowId, {
        name: normalizedName,
        description: description.trim() || null,
      });
      setWorkflow(updated);
      setSavedMessage("Workflow metadata saved. Its definition and execution history are unchanged.");
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Workflow metadata could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function changeLifecycle(action: "archive" | "restore") {
    const isArchiving = action === "archive";
    const message = isArchiving
      ? "Archive this workflow? Its definition and execution history will be retained."
      : "Restore this workflow and make it active again?";
    if (!window.confirm(message)) return;
    setActionError(null);
    setSavedMessage(null);
    try {
      const updated = isArchiving
        ? await archiveWorkflow(workflowId)
        : await restoreWorkflow(workflowId);
      setWorkflow(updated);
      setSavedMessage(isArchiving ? "Workflow archived." : "Workflow restored.");
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Workflow status could not be changed.");
    }
  }

  if (loading) return <LoadingState label="Loading workflow details" />;
  if (loadError || !workflow) {
    return (
      <ErrorState
        title="Workflow details unavailable"
        description={loadError ?? "This workflow could not be found in your workspace."}
        onRetry={() => setReload((value) => value + 1)}
      />
    );
  }

  const graphTasks = workflow.workflow_definition.tasks.map((task) => ({
    task_id: task.task_id,
    agent_type: task.agent_type ?? "unknown",
    dependency_ids: task.dependency_ids ?? [],
    status: "pending" as const,
  }));
  const isArchived = workflow.status === "archived";

  return (
    <div className="mx-auto max-w-[1200px] min-w-0">
      <Link
        to="/workflows"
        className="mb-5 inline-flex items-center gap-2 text-sm text-[var(--secondary)] transition-colors hover:text-[var(--text)]"
      >
        <ArrowLeft size={15} /> Workflow registry
      </Link>
      <PageHeader
        title={workflow.name}
        description={workflow.description || "No description has been added."}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={isArchived ? "neutral" : "green"}>
              {isArchived ? "Archived" : "Active"}
            </StatusBadge>
            {canManageWorkflows && (
              <Button
                variant="secondary"
                onClick={() => void changeLifecycle(isArchived ? "restore" : "archive")}
              >
                {isArchived ? "Restore workflow" : "Archive workflow"}
              </Button>
            )}
          </div>
        }
      />

      {actionError && (
        <p role="alert" className="mb-4 rounded-lg border border-[var(--error)]/30 p-3 text-sm text-[var(--error)]">
          {actionError}
        </p>
      )}
      {savedMessage && (
        <p role="status" className="mb-4 rounded-lg border border-[var(--success)]/30 p-3 text-sm text-[var(--success)]">
          {savedMessage}
        </p>
      )}

      <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
          <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
            <GitBranch size={14} /> Definition version
          </div>
          <p className="mt-2 text-lg font-semibold">v{workflow.version}</p>
        </div>
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
          <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
            <Workflow size={14} /> Planned steps
          </div>
          <p className="mt-2 text-lg font-semibold">{workflow.workflow_definition.tasks.length}</p>
        </div>
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
          <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
            <Play size={14} /> Executions
          </div>
          <p className="mt-2 text-lg font-semibold">{workflow.execution_count ?? executions.length}</p>
        </div>
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
          <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
            <Clock3 size={14} /> Last updated
          </div>
          <p className="mt-2 text-sm font-medium">{formatDate(workflow.updated_at)}</p>
        </div>
      </div>

      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(300px,.8fr)]">
        <section className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 md:p-6">
          <div className="mb-5">
            <h2 className="text-base font-semibold">Workflow plan</h2>
            <p className="mt-1 text-sm text-[var(--secondary)]">
              Dependency order and task assignments. Task inputs and tool arguments are not shown.
            </p>
          </div>
          {graphTasks.length ? (
            <WorkflowPlanGraph tasks={graphTasks} />
          ) : (
            <EmptyState title="No planned steps" description="This workflow has no task definitions." />
          )}
          <div className="mt-6 space-y-3">
            {workflow.workflow_definition.tasks.map((step, index) => (
              <article
                key={step.task_id}
                className="flex min-w-0 gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] p-4"
              >
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-[var(--accent-soft)] text-xs font-semibold text-[var(--accent)]">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <h3 className="break-words text-sm font-semibold">{step.task_id}</h3>
                  <p className="mt-1 text-xs text-[var(--secondary)]">
                    {step.agent_type ?? "Agent"} ·{" "}
                    {step.dependency_ids?.length
                      ? `Depends on ${step.dependency_ids.join(", ")}`
                      : "No dependencies"}
                  </p>
                  {step.description && (
                    <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[var(--secondary)]">
                      {step.description}
                    </p>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>

        <div className="space-y-6">
          {canManageWorkflows && (
            <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="mb-4 flex items-center gap-2">
                <Edit3 size={15} className="text-[var(--accent)]" />
                <h2 className="text-sm font-semibold">Workflow metadata</h2>
              </div>
              <form className="space-y-4" onSubmit={(event) => void saveMetadata(event)}>
                <div>
                  <label htmlFor="workflow-name" className="mb-1.5 block text-xs font-medium text-[var(--secondary)]">
                    Name
                  </label>
                  <input
                    id="workflow-name"
                    value={name}
                    maxLength={200}
                    required
                    onChange={(event) => setName(event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2.5 text-sm focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/20"
                  />
                </div>
                <div>
                  <label htmlFor="workflow-description" className="mb-1.5 block text-xs font-medium text-[var(--secondary)]">
                    Description
                  </label>
                  <textarea
                    id="workflow-description"
                    value={description}
                    maxLength={2_000}
                    rows={4}
                    onChange={(event) => setDescription(event.target.value)}
                    className="w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2.5 text-sm leading-6 focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/20"
                  />
                  <p className="mt-1 text-right text-[11px] text-[var(--muted)]">
                    {description.length.toLocaleString()} / 2,000
                  </p>
                </div>
                <p className="text-xs leading-5 text-[var(--muted)]">
                  Editing metadata does not change this version’s workflow definition or execution history.
                </p>
                <Button type="submit" disabled={saving}>
                  {saving ? "Saving…" : "Save changes"}
                </Button>
              </form>
            </section>
          )}

          <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">Execution history</h2>
                <p className="mt-1 text-xs text-[var(--muted)]">Runs linked to this workflow version</p>
              </div>
              <Link
                to={`/executions?workflow_id=${encodeURIComponent(workflow.id)}`}
                className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent)] hover:underline"
              >
                View all <ArrowRight size={13} />
              </Link>
            </div>
            {historyLoading ? (
              <p role="status" className="py-5 text-center text-sm text-[var(--secondary)]">
                Loading execution history…
              </p>
            ) : historyError ? (
              <div role="alert" className="rounded-lg border border-[var(--error)]/30 p-3 text-sm text-[var(--error)]">
                <p>{historyError}</p>
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-3"
                  onClick={() => setReload((value) => value + 1)}
                >
                  Retry
                </Button>
              </div>
            ) : executions.length === 0 ? (
              <EmptyState
                title="No executions yet"
                description="New runs of this workflow will appear here."
              />
            ) : (
              <ol className="divide-y divide-[var(--border)]">
                {executions.map((execution) => (
                  <li
                    key={execution.execution_id}
                    className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium">{execution.execution_id}</p>
                      <p className="mt-1 text-[11px] text-[var(--muted)]">
                        {formatDate(execution.created_at)}
                      </p>
                    </div>
                    <StatusBadge tone={statusTone(execution.status)}>{execution.status}</StatusBadge>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

export default function WorkflowsPage({
  canManageWorkflows = true,
}: {
  canManageWorkflows?: boolean;
}) {
  const { workflowId } = useParams();
  return workflowId ? (
    <WorkflowDetailPage workflowId={workflowId} canManageWorkflows={canManageWorkflows} />
  ) : (
    <WorkflowRegistryPage />
  );
}
