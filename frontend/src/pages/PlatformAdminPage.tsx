import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Building2, RefreshCw, Shield, Users, Workflow } from "lucide-react";
import { apiBaseUrl } from "../api/config";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";

type Overview = { users: { total: number; active: number; pending: number; suspended: number }; workspaces: number; workflows: number; executions: number; recent_activity: { action: string; target_user_id: string; occurred_at: string }[] };
type UserRow = { id: string; email: string; account_status: string; created_at: string; last_login_at: string | null; email_verified_at?: string | null; workspaces: { name: string; role: string }[] };
type WorkspaceRow = { id: string; name: string; slug: string; status: string; owner: { email: string }; members: { email: string; role: string }[]; workflow_count: number; execution_count: number };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}/platform-admin${path}`, { credentials: "include", ...init, headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers } });
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? "Operator access is required." : "Platform data could not be loaded.");
  return response.json() as Promise<T>;
}

export default function PlatformAdminPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceRow[]>([]);
  const [tab, setTab] = useState<"users" | "workspaces">("users");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState<UserRow | null>(null);
  const [selectedUser, setSelectedUser] = useState<UserRow | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const activeLoad = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    activeLoad.current?.abort();
    const controller = new AbortController();
    activeLoad.current = controller;
    setBusy(true); setError("");
    try {
      const [stats, userRows, workspaceRows] = await Promise.all([
        request<Overview>("/overview", { signal: controller.signal }),
        request<{ items: UserRow[] }>(`/users?q=${encodeURIComponent(query)}${status ? `&status=${status}` : ""}`, { signal: controller.signal }),
        request<{ items: WorkspaceRow[] }>(`/workspaces?q=${encodeURIComponent(query)}`, { signal: controller.signal }),
      ]);
      setOverview(stats); setUsers(userRows.items); setWorkspaces(workspaceRows.items);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Platform data could not be loaded.");
    } finally {
      if (activeLoad.current === controller) { activeLoad.current = null; setBusy(false); }
    }
  }, [query, status]);
  useEffect(() => {
    void refresh();
    return () => activeLoad.current?.abort();
  }, [refresh]);
  async function setUserStatus(user: UserRow, next: string) {
    setError("");
    try {
      await request(`/users/${user.id}/status`, { method: "PATCH", body: JSON.stringify({ status: next }) });
      setConfirming(null);
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Account update failed."); }
  }
  async function showUserDetails(user: UserRow) {
    setSelectedUser(null);
    setDetailLoading(true);
    try { setSelectedUser(await request<UserRow>(`/users/${user.id}`)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "User details could not be loaded."); }
    finally { setDetailLoading(false); }
  }

  return <div className="mx-auto max-w-7xl space-y-6">
    <PageHeader title="Platform administration" description="Operator-only controls for accounts and workspace activity." />
    <div className="flex items-center gap-2 rounded-xl border border-[var(--accent)]/30 bg-[var(--accent-soft)] px-4 py-3 text-sm"><Shield size={17} className="text-[var(--accent)]"/><span>Platform operator access</span><span className="ml-auto text-xs text-[var(--muted)]">Separate from workspace roles</span></div>
    {error && <div role="alert" className="flex items-center justify-between rounded-xl border border-[var(--error)]/30 bg-[var(--error)]/10 p-4 text-sm"><span>{error}</span><button onClick={() => void refresh()} className="inline-flex items-center gap-2 font-medium"><RefreshCw size={15}/> Retry</button></div>}
    {overview ? <div className="grid grid-cols-2 gap-3 lg:grid-cols-5"><MetricCard label="Users" value={`${overview.users.total}`} change={`${overview.users.active} active · ${overview.users.pending} pending`} icon={<Users size={17}/>} /><MetricCard label="Suspended" value={`${overview.users.suspended}`} change="Accounts currently suspended" tone="red"/><MetricCard label="Workspaces" value={`${overview.workspaces}`} change="Across the platform" icon={<Building2 size={17}/>} /><MetricCard label="Workflows" value={`${overview.workflows}`} change="Persisted definitions" icon={<Workflow size={17}/>} /><MetricCard label="Executions" value={`${overview.executions}`} change="Persisted execution records" icon={<Activity size={17}/>} /></div> : !error && <div role="status" className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">Loading platform metrics…</div>}
    {overview && <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h2 className="text-sm font-semibold">Recent platform activity</h2>{overview.recent_activity.length ? <div className="mt-3 divide-y divide-[var(--border)]">{overview.recent_activity.map((activity, index) => <div key={`${activity.target_user_id}-${activity.occurred_at}-${index}`} className="flex flex-wrap justify-between gap-2 py-2 text-xs"><span className="font-medium">{activity.action.replace("user_", "User ")} · {activity.target_user_id}</span><time className="text-[var(--muted)]">{new Date(activity.occurred_at).toLocaleString()}</time></div>)}</div> : <p className="mt-2 text-xs text-[var(--muted)]">No platform actions have been recorded.</p>}</section>}
    <section className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex flex-col gap-3 border-b border-[var(--border)] p-4 sm:flex-row sm:items-center"><div className="flex rounded-lg bg-[var(--surface-alt)] p-1"><button onClick={() => setTab("users")} className={`rounded-md px-3 py-2 text-sm ${tab === "users" ? "bg-[var(--surface)]" : "text-[var(--muted)]"}`}>Users</button><button onClick={() => setTab("workspaces")} className={`rounded-md px-3 py-2 text-sm ${tab === "workspaces" ? "bg-[var(--surface)]" : "text-[var(--muted)]"}`}>Workspaces</button></div><input aria-label="Search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tab === "users" ? "Search email" : "Search name or slug"} className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2 text-sm"/>{tab === "users" && <select aria-label="Account status" value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3 py-2 text-sm"><option value="">All statuses</option><option value="active">Active</option><option value="pending">Pending</option><option value="suspended">Suspended</option></select>}<button aria-label="Refresh" onClick={() => void refresh()} disabled={busy} className="rounded-lg border border-[var(--border)] p-2 text-[var(--secondary)]"><RefreshCw size={16} className={busy ? "animate-spin" : ""}/></button></div>
      {tab === "users" ? <div className="divide-y divide-[var(--border)]">{users.map((user) => <div key={user.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{user.email}</div><div className="mt-1 text-xs text-[var(--muted)]">{user.workspaces.map((w) => `${w.name} · ${w.role}`).join(", ") || "No workspace memberships"}</div><div className="mt-1 text-xs text-[var(--muted)]">Created {new Date(user.created_at).toLocaleDateString()} · Last login {user.last_login_at ? new Date(user.last_login_at).toLocaleDateString() : "Never"}</div></div><span className="w-fit rounded-full bg-[var(--surface-alt)] px-2.5 py-1 text-xs capitalize">{user.account_status}</span><button disabled={busy} onClick={() => void showUserDetails(user)} className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs font-medium hover:bg-[var(--surface-alt)]">Details</button>{user.account_status !== "deleted" && <button disabled={busy} onClick={() => setConfirming(user)} className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs font-medium hover:bg-[var(--surface-alt)]">{user.account_status === "suspended" ? "Reactivate" : "Suspend"}</button>}</div>)}{users.length === 0 && !busy && <p className="p-8 text-center text-sm text-[var(--muted)]">No users match this search.</p>}</div> : <div className="divide-y divide-[var(--border)]">{workspaces.map((workspace) => <div key={workspace.id} className="p-4"><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium">{workspace.name}</span><span className="text-xs text-[var(--muted)]">{workspace.slug}</span><span className="ml-auto rounded-full bg-[var(--surface-alt)] px-2.5 py-1 text-xs capitalize">{workspace.status}</span></div><div className="mt-2 text-xs text-[var(--secondary)]">Owner: {workspace.owner.email} · {workspace.members.length} members · {workspace.workflow_count} workflows · {workspace.execution_count} executions</div><div className="mt-1 text-xs text-[var(--muted)]">{workspace.members.map((member) => `${member.email} (${member.role})`).join(" · ")}</div></div>)}{workspaces.length === 0 && !busy && <p className="p-8 text-center text-sm text-[var(--muted)]">No workspaces match this search.</p>}</div>}
    </section>
    {confirming && <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"><section role="alertdialog" aria-modal="true" aria-labelledby="account-confirm-title" className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-2xl"><h2 id="account-confirm-title" className="text-lg font-semibold">{confirming.account_status === "suspended" ? "Reactivate account?" : "Suspend account?"}</h2><p className="mt-2 text-sm text-[var(--secondary)]">{confirming.account_status === "suspended" ? `Restore sign-in access for ${confirming.email}?` : `Suspend ${confirming.email}? Their active sessions will be revoked.`}</p><div className="mt-6 flex justify-end gap-2"><button onClick={() => setConfirming(null)} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm">Cancel</button><button disabled={busy} onClick={() => void setUserStatus(confirming, confirming.account_status === "suspended" ? "active" : "suspended")} className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-white disabled:opacity-60">Confirm {confirming.account_status === "suspended" ? "reactivation" : "suspension"}</button></div></section></div>}
    {(detailLoading || selectedUser) && <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"><section role="dialog" aria-modal="true" aria-labelledby="user-detail-title" className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-2xl"><div className="flex items-center justify-between"><h2 id="user-detail-title" className="text-lg font-semibold">User details</h2><button onClick={() => setSelectedUser(null)} aria-label="Close user details" className="rounded-md px-2 py-1 text-sm text-[var(--muted)]">Close</button></div>{detailLoading ? <p role="status" className="mt-4 text-sm text-[var(--muted)]">Loading user details…</p> : selectedUser && <div className="mt-4 space-y-3 text-sm"><p><span className="text-[var(--muted)]">Email:</span> {selectedUser.email}</p><p><span className="text-[var(--muted)]">Status:</span> {selectedUser.account_status}</p><p><span className="text-[var(--muted)]">Created:</span> {new Date(selectedUser.created_at).toLocaleString()}</p><p><span className="text-[var(--muted)]">Last login:</span> {selectedUser.last_login_at ? new Date(selectedUser.last_login_at).toLocaleString() : "Never"}</p><p><span className="text-[var(--muted)]">Email verified:</span> {selectedUser.email_verified_at ? new Date(selectedUser.email_verified_at).toLocaleString() : "No"}</p><h3 className="pt-2 font-medium">Workspace memberships</h3>{selectedUser.workspaces.length ? selectedUser.workspaces.map((workspace) => <p key={workspace.name}>{workspace.name} · {workspace.role}</p>) : <p className="text-[var(--muted)]">No workspace memberships.</p>}</div>}</section></div>}
  </div>;
}
