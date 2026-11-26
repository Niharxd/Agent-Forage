import { Activity, Bot, Boxes, ChevronLeft, ChevronRight, LayoutDashboard, Settings2, Workflow, X } from "lucide-react";
import { NavLink } from "react-router-dom";

const items = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/workflows", label: "Workflows", icon: Workflow },
  { to: "/executions", label: "Executions", icon: Activity },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/tools", label: "Tools", icon: Boxes },
  { to: "/settings", label: "Settings", icon: Settings2 },
];

type SidebarProps = { collapsed: boolean; onToggleCollapse: () => void; mobileOpen: boolean; onToggleMobile: () => void; isOperator: boolean };

export function Sidebar({ collapsed, onToggleCollapse, mobileOpen, onToggleMobile, isOperator }: SidebarProps) {
  const visibleItems = isOperator ? items : items.filter(({ to }) => to !== "/agents" && to !== "/tools");
  return <>
    <aside className={`fixed inset-y-0 left-0 z-40 flex w-[260px] flex-col border-r border-[var(--border)] bg-[var(--sidebar)] px-3 py-5 transition-all md:static md:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"} ${collapsed ? "md:w-[78px]" : "md:w-[248px]"}`} aria-label="Sidebar navigation">
      <div className={`mb-7 flex items-center justify-between px-2 ${collapsed ? "h-11" : "h-[74px]"}`}>
        <div className="flex min-w-0 items-center">
          <img src="/assets/agentforge-logo.png" alt="AgentForge" title="AgentForge" className={`shrink-0 object-contain ${collapsed ? "h-10 w-10" : "h-[70px] w-[112px]"}`} />
          {!collapsed && <span className="ml-2 text-[10px] font-medium uppercase tracking-[.15em] text-[var(--muted)]">Orchestration</span>}
        </div>
        <button type="button" onClick={onToggleMobile} aria-label="Close navigation" className="rounded-md p-1 text-[var(--muted)] md:hidden"><X size={17} /></button>
      </div>
      <div className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[.16em] text-[var(--muted)]">Workspace</div>
      <nav aria-label="Primary navigation" className="space-y-1">
        {visibleItems.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === "/"} onClick={onToggleMobile} title={collapsed ? label : undefined} className={({ isActive }) => `group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-colors ${isActive ? "bg-gradient-to-r from-blue-500/15 to-violet-500/10 text-[var(--text)] before:absolute before:inset-y-2 before:left-0 before:w-[2px] before:rounded-full before:bg-gradient-to-b before:from-blue-400 before:to-violet-500" : "text-[var(--secondary)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"} ${collapsed ? "md:justify-center md:px-0" : ""}`}><Icon size={17} strokeWidth={1.8} />{!collapsed && <span>{label}</span>}</NavLink>)}
      </nav>
      <div className="mt-auto">
        <div className={`mb-3 rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] p-3 ${collapsed ? "md:hidden" : ""}`}><div className="text-xs font-medium">{isOperator ? "Operator workspace" : "Personal workspace"}</div><p className="mt-2 text-[11px] leading-relaxed text-[var(--muted)]">{isOperator ? "Workflows, agents, tools, and execution history." : "Your workflows and execution history."}</p></div>
        <button type="button" onClick={onToggleCollapse} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} className="hidden w-full items-center justify-center rounded-lg border border-[var(--border)] py-2 text-[var(--muted)] hover:bg-white/[.04] md:flex">{collapsed ? <ChevronRight size={16}/> : <><ChevronLeft size={16}/><span className="ml-2 text-xs">Collapse sidebar</span></>}</button>
      </div>
    </aside>
    {mobileOpen && <button type="button" aria-label="Close navigation overlay" onClick={onToggleMobile} className="fixed inset-0 z-30 bg-black/60 md:hidden"/>}
  </>;
}
