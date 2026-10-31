import { MoonStar, Palette, ShieldCheck, SunMedium } from "lucide-react";
import { Button } from "../components/Button";
import { Dropdown } from "../components/Dropdown";
import { PageHeader } from "../components/PageHeader";
import { themeOptions } from "../data/demoData";
import { useTheme } from "../theme/ThemeContext";

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Appearance and account placeholders for the frontend shell."
      />

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
              <Palette className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-[var(--text)]">Appearance</h2>
              <p className="text-sm text-[var(--secondary)]">Select a theme for the current workspace.</p>
            </div>
          </div>

          <div className="space-y-4">
            <Dropdown
              label="Theme selection"
              value={theme}
              options={themeOptions.map((option) => ({ value: option.value, label: option.label }))}
              onChange={(value) => setTheme(value as "light" | "dark" | "system")}
            />

            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-alt)] p-3">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-medium text-[var(--text)]">Preview</span>
                <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1 text-[11px] text-[var(--secondary)]">
                  {theme === "dark" ? <MoonStar className="h-3 w-3" /> : <SunMedium className="h-3 w-3" />}
                  {theme === "system" ? "System theme" : `${theme.charAt(0).toUpperCase()}${theme.slice(1)} theme`}
                </div>
              </div>
              <div className="h-28 rounded-xl bg-[var(--bg)] p-3 text-sm text-[var(--text)]">
                Interface tune: a cleaner developer environment with clearer hierarchy and calmer density.
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <div className="mb-3 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
                <ShieldCheck className="h-4 w-4" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-[var(--text)]">Account placeholder</h3>
              </div>
            </div>
            <div className="space-y-2 text-sm text-[var(--secondary)]">
              <div>Organization: AgentForge</div>
              <div>User: Nihar</div>
              <div>Role: Product engineering</div>
            </div>
          </div>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <h3 className="text-base font-semibold text-[var(--text)]">Application information</h3>
            <div className="mt-3 space-y-2 text-sm text-[var(--secondary)]">
              <div>Frontend: React + TypeScript + Vite</div>
              <div>Design system: AgentForge foundation</div>
              <div>Theme persistence: localStorage</div>
            </div>
            <div className="mt-4">
              <Button variant="secondary">Save preferences</Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
