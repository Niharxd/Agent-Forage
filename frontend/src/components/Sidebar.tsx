import { Menu, Sparkles, X } from "lucide-react";
import { NavLink } from "react-router-dom";
import { navigationItems } from "../data/demoData";

type SidebarProps = {
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onToggleMobile: () => void;
};

export function Sidebar({ collapsed, onToggleCollapse, mobileOpen, onToggleMobile }: SidebarProps) {
  const widthClass = collapsed ? "md:w-[92px]" : "md:w-[240px]";

  return (
    <>
      <div
        className={`fixed inset-y-0 left-0 z-40 flex w-[86%] max-w-[260px] flex-col border-r border-[var(--border)] bg-[var(--sidebar)] p-4 transition-transform duration-200 md:static md:w-auto md:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"} ${widthClass}`}
        aria-label="Sidebar navigation"
      >
        <div className="mb-4 flex items-center justify-between gap-3 border-b border-[var(--border)] pb-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
              <Sparkles className="h-4 w-4" />
            </div>
            {!collapsed ? <div className="text-sm font-semibold tracking-[-0.02em] text-[var(--text)]">AgentForge</div> : null}
          </div>
          <button
            type="button"
            className="hidden rounded-md p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-alt)] md:inline-flex"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={onToggleCollapse}
          >
            {collapsed ? <Menu className="h-4 w-4" /> : <X className="h-4 w-4" />}
          </button>
        </div>

        <div className="mb-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-2.5">
          <div className="text-[10px] uppercase tracking-[0.12em] text-[var(--muted)]">Workspace</div>
          {!collapsed ? <div className="mt-2 text-sm font-medium text-[var(--text)]">Core operations</div> : null}
        </div>

        <nav aria-label="Primary navigation" className="space-y-1.5">
          {navigationItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={() => onToggleMobile()}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                      : "text-[var(--secondary)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
                  } ${collapsed ? "justify-center" : ""}`
                }
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {!collapsed ? <span>{item.label}</span> : null}
              </NavLink>
            );
          })}
        </nav>

        <div className="mt-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent-soft)] text-[var(--accent)] text-xs font-medium">N</div>
            {!collapsed ? (
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-[var(--text)]">Nihar</div>
                <div className="truncate text-[11px] text-[var(--secondary)]">AgentForge / Core ops</div>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {mobileOpen ? (
        <button
          type="button"
          aria-label="Close navigation overlay"
          onClick={onToggleMobile}
          className="fixed inset-0 z-30 bg-black/20 md:hidden"
        />
      ) : null}
    </>
  );
}
