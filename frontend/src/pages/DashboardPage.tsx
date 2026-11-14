import { Activity, ArrowUpRight, CheckCircle2, CircleDashed, Clock3, Plus, RefreshCw, Workflow, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { listExecutions, type Execution, type ExecutionStatus } from "../api/executions";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";

const tones: Record<ExecutionStatus, "blue" | "violet" | "green" | "red" | "neutral"> = { pending: "blue", running: "violet", completed: "green", failed: "red", cancelled: "neutral" };
const labels: Record<ExecutionStatus, string> = { pending: "Pending", running: "Running", completed: "Completed", failed: "Failed", cancelled: "Cancelled" };
function stamp(value: string) { const date = new Date(value); return Number.isNaN(+date) ? "Unknown time" : date.toLocaleString(); }

export default function DashboardPage() {
  const [items, setItems] = useState<Execution[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const load = useCallback((signal: AbortSignal) => listExecutions({ limit: 50, offset: 0, status: undefined, search: "" }, signal), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null);
    load(controller.signal).then((result) => { if (!controller.signal.aborted) { setItems(result.items); setTotal(result.total); } }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Execution data could not be loaded."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [load, refresh]);
  useEffect(() => {
    if (!items.some((item) => item.status === "pending" || item.status === "running")) return undefined;
    const timer = window.setInterval(() => setRefresh((value) => value + 1), 7000);
    return () => window.clearInterval(timer);
  }, [items]);
  const metrics = useMemo(() => [
    { label: "Total executions", value: total, icon: Workflow, hint: "Persisted in history", color: "text-blue-300" },
    { label: "In progress", value: items.filter((item) => item.status === "running").length, icon: Activity, hint: "Currently running", color: "text-violet-300" },
    { label: "Completed", value: items.filter((item) => item.status === "completed").length, icon: CheckCircle2, hint: "In recent records", color: "text-emerald-300" },
    { label: "Failed", value: items.filter((item) => item.status === "failed").length, icon: XCircle, hint: "In recent records", color: "text-rose-300" },
  ], [items, total]);
  return <div className="mx-auto max-w-[1440px]">
    <PageHeader title="Command center" description="A live view of persisted workflow execution across your orchestration workspace." actions={<><Button variant="secondary" onClick={() => setRefresh((v) => v + 1)} disabled={loading}><RefreshCw className="mr-2 h-4 w-4"/>Refresh</Button><Link to="/workflows"><Button><Plus className="mr-2 h-4 w-4"/>New workflow</Button></Link></>}/>
    <section className="mb-6 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex flex-col justify-between gap-5 p-6 md:flex-row md:items-center md:p-8"><div><div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[.16em] text-blue-300"><span className="h-1.5 w-1.5 rounded-full bg-blue-400"/>Orchestration overview</div><h2 className="max-w-xl text-2xl font-semibold tracking-tight md:text-[28px]">Your workflows, clearly in motion.</h2><p className="mt-2 max-w-xl text-sm leading-6 text-[var(--secondary)]">Review execution health, inspect task progress, and prepare the next task for your agents.</p></div><Link to="/workflows" className="shrink-0"><Button variant="secondary">Create a workflow<ArrowUpRight className="ml-2 h-4 w-4"/></Button></Link></div>
      <div className="flex items-center gap-2 border-t border-[var(--border)] bg-black/10 px-6 py-3 text-xs text-[var(--muted)]"><Activity size={14} className="text-cyan-300"/>Execution monitor <span className="mx-1 text-[var(--border)]">/</span> auto-refreshes while work is active</div>
    </section>
    <section aria-label="Execution statistics" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{metrics.map(({ label, value, icon: Icon, hint, color }) => <article key={label} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between"><span className="text-xs font-medium text-[var(--secondary)]">{label}</span><Icon size={16} className={color}/></div><div className="mt-4 text-3xl font-semibold tracking-tight">{loading ? "–" : value}</div><div className="mt-1 text-[11px] text-[var(--muted)]">{hint}</div></article>)}</section>
    <section className="mt-6 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4"><div><h2 className="text-sm font-semibold">Recent executions</h2><p className="mt-1 text-xs text-[var(--muted)]">Latest persisted activity</p></div><Link to="/executions" className="text-xs font-medium text-blue-300 hover:text-blue-200">View history <ArrowUpRight className="ml-1 inline" size={13}/></Link></div>
      {error ? <div className="m-5 rounded-lg border border-rose-400/30 bg-rose-400/5 p-4" role="alert"><p className="text-sm text-rose-200">{error}</p><Button variant="secondary" size="sm" className="mt-3" onClick={() => setRefresh((v) => v + 1)}>Retry</Button></div> : loading ? <div className="space-y-3 p-5" aria-label="Loading executions">{[1,2,3].map((n)=><div key={n} className="h-12 animate-pulse rounded-lg bg-white/[.035]"/>)}</div> : items.length === 0 ? <div className="p-6"><EmptyState title="No execution activity yet" description="Create a workflow to prepare a validated plan for execution." action={<Link to="/workflows"><Button><Plus className="mr-2 h-4 w-4"/>Create workflow</Button></Link>}/></div> : <div className="divide-y divide-[var(--border)]">{items.slice(0, 8).map((execution) => { const tasks = Object.values(execution.task_results); const complete = tasks.filter((task) => task.status === "completed").length; const pending = tasks.filter((task) => task.status === "pending" || task.status === "running").length; return <Link to="/executions" key={execution.execution_id} className="flex flex-col gap-3 px-5 py-4 transition-colors hover:bg-white/[.025] sm:flex-row sm:items-center"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] text-[var(--muted)]"><CircleDashed size={16}/></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{execution.workflow_name}</span><span className="mt-1 block truncate font-mono text-[10px] text-[var(--muted)]">{execution.execution_id}</span></span><span className="flex items-center gap-2 text-xs text-[var(--muted)]"><Clock3 size={13}/>{stamp(execution.created_at)}</span><span className="min-w-[108px] text-xs text-[var(--secondary)]">{complete}/{tasks.length} tasks{pending ? ` · ${pending} active` : ""}</span><StatusBadge tone={tones[execution.status]}>{labels[execution.status]}</StatusBadge></Link>; })}</div>}
    </section>
    <p className="mt-4 text-[11px] text-[var(--muted)]">Statistics reflect the latest 50 execution records returned by the API. Totals use the server’s full history count.</p>
  </div>;
}
