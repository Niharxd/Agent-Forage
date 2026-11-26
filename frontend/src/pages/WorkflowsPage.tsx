import { ArrowRight, CheckCircle2, Plus, Search, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { createPlannedWorkflow, getWorkflow, listWorkflows, type PrepareResponse, type WorkflowRecord } from "../api/executions";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";

function date(value: string) { const parsed = new Date(value); return Number.isNaN(+parsed) ? "Unknown" : parsed.toLocaleString(); }

export default function WorkflowsPage() {
  const [items, setItems] = useState<WorkflowRecord[]>([]);
  const [search, setSearch] = useState("");
  const [task, setTask] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [success, setSuccess] = useState<PrepareResponse | null>(null);
  const [reload, setReload] = useState(0);
  const [searchParams] = useSearchParams();
  const selectedWorkflowId = searchParams.get("workflow");
  useEffect(() => { const controller = new AbortController(); setLoading(true); setListError(null); listWorkflows(controller.signal).then((data) => { if (!controller.signal.aborted) setItems(data.items); }).catch((reason: unknown) => { if (!controller.signal.aborted) setListError(reason instanceof Error ? reason.message : "Workflow list could not be loaded."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, [reload]);
  useEffect(() => {
    if (!selectedWorkflowId || loading || items.some((workflow) => workflow.id === selectedWorkflowId)) return undefined;
    const controller = new AbortController();
    getWorkflow(selectedWorkflowId, controller.signal).then((workflow) => {
      if (!controller.signal.aborted) {
        setItems((current) => current.some((item) => item.id === workflow.id) ? current : [workflow, ...current]);
      }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setListError(reason instanceof Error ? reason.message : "Workflow could not be opened.");
    });
    return () => controller.abort();
  }, [items, loading, selectedWorkflowId]);
  useEffect(() => {
    if (!selectedWorkflowId || loading || !items.some((workflow) => workflow.id === selectedWorkflowId)) return;
    document.getElementById(`workflow-${selectedWorkflowId}`)?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [items, loading, selectedWorkflowId]);
  const filtered = useMemo(() => items.filter((workflow) => `${workflow.name} ${workflow.description ?? ""}`.toLowerCase().includes(search.toLowerCase())), [items, search]);
  async function prepare(event: React.FormEvent<HTMLFormElement>) { event.preventDefault(); if (submitting || !task.trim()) return; setSubmitting(true); setError(null); setSuccess(null); try { const result = await createPlannedWorkflow(task.trim()); setSuccess(result); setTask(""); setReload((value) => value + 1); } catch (reason) { setError(reason instanceof Error ? reason.message : "Workflow preparation failed."); } finally { setSubmitting(false); } }
  return <div className="mx-auto max-w-[1440px]">
    <PageHeader title="Workflows" description="Turn a task into a validated plan, then decide when it should run." actions={<a href="#new-workflow"><Button><Plus className="mr-2 h-4 w-4"/>New workflow</Button></a>}/>
    <div className="mb-6 grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
      <section id="new-workflow" className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 md:p-6">
        <div className="mb-5 flex items-start gap-3"><div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-blue-500/10 text-blue-300"><Workflow size={18}/></div><div><h2 className="text-sm font-semibold">Prepare a workflow</h2><p className="mt-1 text-xs leading-5 text-[var(--secondary)]">Describe the outcome. The Planner will create and persist a pending plan without starting its tasks.</p></div></div>
        <form onSubmit={prepare} className="space-y-3"><label htmlFor="task-description" className="text-xs font-medium text-[var(--secondary)]">Task instructions</label><textarea id="task-description" value={task} onChange={(event) => setTask(event.target.value)} maxLength={10000} rows={5} required placeholder="Example: Research the latest public guidance on X and prepare a concise summary with source links." className="w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3.5 py-3 text-sm leading-6 text-[var(--text)] placeholder:text-[var(--muted)] focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-400/20"/><div className="flex flex-wrap items-center justify-between gap-3"><span className="text-[11px] text-[var(--muted)]">{task.length.toLocaleString()} / 10,000 characters</span><Button type="submit" disabled={submitting || !task.trim()}>{submitting ? "Preparing plan…" : "Prepare for review"}<ArrowRight className="ml-2 h-4 w-4"/></Button></div></form>
        {error && <div role="alert" className="mt-4 rounded-lg border border-rose-400/30 bg-rose-400/5 p-3 text-sm text-rose-200">{error}</div>}
        {success && <div role="status" className="mt-4 rounded-lg border border-emerald-400/30 bg-emerald-400/5 p-4"><div className="flex items-center gap-2 text-sm font-medium text-emerald-200"><CheckCircle2 size={16}/>Plan prepared and saved</div><p className="mt-1 text-xs text-[var(--secondary)]">{success.workflow.name} · {success.execution.workflow_plan?.length ?? 0} tasks · execution is pending and has not started.</p><Link to="/executions" className="mt-3 inline-flex text-xs font-medium text-blue-300 hover:text-blue-200">Review in execution history <ArrowRight className="ml-1" size={14}/></Link></div>}
      </section>
      <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 md:p-6"><div className="text-[11px] font-semibold uppercase tracking-[.14em] text-violet-300">Execution control</div><h2 className="mt-3 text-lg font-semibold">Plan first. Start explicitly.</h2><p className="mt-2 max-w-lg text-sm leading-6 text-[var(--secondary)]">Preparing a workflow validates and stores the draft with a pending execution. No agent or tool task runs until you call the start action from execution controls.</p><div className="mt-5 flex flex-wrap gap-2"><StatusBadge tone="blue">Pending review</StatusBadge><StatusBadge tone="violet">Explicit start required</StatusBadge></div><div className="mt-5 rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] p-3 text-xs leading-5 text-[var(--muted)]">Submitted task descriptions are persisted by the backend. Do not include credentials or information that must not be retained.</div></section>
    </div>
    <section className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex flex-col gap-3 border-b border-[var(--border)] p-5 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="text-sm font-semibold">Workflow registry</h2><p className="mt-1 text-xs text-[var(--muted)]">Persisted definitions from the backend</p></div><label className="relative sm:w-72"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]"/><input aria-label="Search workflows" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search workflows" className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] py-2 pl-9 pr-3 text-xs focus:border-blue-400 focus:outline-none"/></label></div>
      {listError ? <div role="alert" className="m-5 rounded-lg border border-rose-400/30 p-4 text-sm text-rose-200">{listError}<Button variant="secondary" size="sm" className="ml-3" onClick={() => setReload((v) => v + 1)}>Retry</Button></div> : loading ? <div className="space-y-3 p-5">{[1,2,3].map((n)=><div key={n} className="h-14 animate-pulse rounded-lg bg-white/[.035]"/>)}</div> : filtered.length === 0 ? <div className="p-6"><EmptyState title={search ? "No matching workflows" : "No saved workflows yet"} description={search ? "Try another name or description." : "Preparing your first task creates a validated workflow definition."}/></div> : <div className="divide-y divide-[var(--border)]">{filtered.map((workflow) => <article id={`workflow-${workflow.id}`} key={workflow.id} className={`flex flex-col gap-2 px-5 py-4 transition-colors sm:flex-row sm:items-center ${workflow.id === selectedWorkflowId ? "bg-[var(--accent-soft)] ring-1 ring-inset ring-[var(--accent)]/40" : ""}`}><div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] text-violet-300"><Workflow size={16}/></div><div className="min-w-0 flex-1"><h3 className="truncate text-sm font-medium">{workflow.name}</h3><p className="mt-1 truncate text-xs text-[var(--secondary)]">{workflow.description || "No description"}</p></div><span className="text-xs text-[var(--muted)]">v{workflow.version} · {workflow.workflow_definition.tasks.length} tasks</span><span className="text-xs text-[var(--muted)]">Updated {date(workflow.updated_at)}</span><StatusBadge tone="blue">Saved</StatusBadge></article>)}</div>}
    </section>
  </div>;
}
