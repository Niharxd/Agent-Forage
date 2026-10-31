import { Bell, ChevronRight, Menu, Search, Settings } from "lucide-react";
import { useLocation } from "react-router-dom";
import { navigationItems } from "../data/demoData";
import { Button } from "./Button";
import { ThemeToggle } from "./ThemeToggle";

type HeaderProps = {
  onMenuClick: () => void;
};

export function Header({ onMenuClick }: HeaderProps) {
  const location = useLocation();
  const currentItem = navigationItems.find((item) => item.to === location.pathname) ?? navigationItems[0];

  return (
    <header className="border-b border-[var(--border)] bg-[color:var(--surface)]/90 backdrop-blur-sm">
      <div className="flex items-center gap-3 px-4 py-3 md:px-6">
        <button
          type="button"
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] md:hidden"
          aria-label="Open navigation"
          onClick={onMenuClick}
        >
          <Menu className="h-4 w-4" />
        </button>

        <div className="hidden min-w-0 items-center gap-2 text-sm text-[var(--muted)] md:flex">
          <span>Overview</span>
          <ChevronRight className="h-3.5 w-3.5" />
          <span className="truncate text-[var(--text)]">{currentItem.label}</span>
        </div>

        <div className="hidden flex-1 items-center justify-center md:flex">
          <div className="relative w-full max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted)]" />
            <input
              aria-label="Search across the interface"
              placeholder="Search workflows, agents..."
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] py-2.5 pl-9 pr-3 text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:border-[var(--primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-soft)]"
            />
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" size="sm" className="hidden md:inline-flex" aria-label="Notifications">
            <Bell className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" className="hidden md:inline-flex" aria-label="Settings shortcut">
            <Settings className="h-4 w-4" />
          </Button>
          <ThemeToggle />
          <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent-soft)] text-xs font-semibold text-[var(--accent)]">N</div>
            <div className="hidden text-xs text-[var(--secondary)] md:block">
              <div className="font-medium text-[var(--text)]">Nihar</div>
              <div>Ops</div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
