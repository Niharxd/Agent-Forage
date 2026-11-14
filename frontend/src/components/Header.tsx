import { ChevronRight, Menu } from "lucide-react";
import { useLocation } from "react-router-dom";
import { navigationItems } from "../data/demoData";
import { ThemeToggle } from "./ThemeToggle";

type HeaderProps = { onMenuClick: () => void };

export function Header({ onMenuClick }: HeaderProps) {
  const location = useLocation();
  const current = navigationItems.find((item) => item.to === location.pathname) ?? navigationItems[0];
  return <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/90 backdrop-blur-xl">
    <div className="flex h-[62px] items-center gap-3 px-4 md:px-8">
      <button type="button" onClick={onMenuClick} aria-label="Open navigation" className="grid h-9 w-9 place-items-center rounded-lg border border-[var(--border)] text-[var(--secondary)] md:hidden"><Menu size={18}/></button>
      <div className="flex items-center gap-2 text-sm"><span className="hidden text-[var(--muted)] sm:inline">AgentForge</span><ChevronRight size={14} className="hidden text-[var(--muted)] sm:block"/><span className="font-medium">{current.label}</span></div>
      <div className="ml-auto flex items-center gap-3"><span className="hidden items-center gap-2 text-[11px] text-[var(--muted)] sm:flex"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400"/>Operator console</span><div className="h-5 w-px bg-[var(--border)]"/><ThemeToggle/></div>
    </div>
  </header>;
}
