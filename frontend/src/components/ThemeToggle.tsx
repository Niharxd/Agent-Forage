import { MoonStar, SunMedium } from "lucide-react";
import { useTheme } from "../theme/ThemeContext";

export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();

  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1">
      <button
        type="button"
        onClick={() => setTheme("light")}
        aria-label="Light mode"
        className={`flex h-8 w-8 items-center justify-center rounded-md transition-colors ${theme === "light" ? "bg-[var(--surface-alt)] text-[var(--text)]" : "text-[var(--muted)]"}`}
      >
        <SunMedium className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() => setTheme("dark")}
        aria-label="Dark mode"
        className={`flex h-8 w-8 items-center justify-center rounded-md transition-colors ${theme === "dark" ? "bg-[var(--surface-alt)] text-[var(--text)]" : "text-[var(--muted)]"}`}
      >
        <MoonStar className="h-4 w-4" />
      </button>
      <div className="flex h-8 items-center rounded-md bg-[var(--surface-alt)] px-2 text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--secondary)]">
        {resolvedTheme === "dark" ? "Dark" : "Light"}
      </div>
    </div>
  );
}
