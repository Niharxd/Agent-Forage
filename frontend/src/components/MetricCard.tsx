import type { ReactNode } from "react";

type MetricCardProps = {
  label: string;
  value: string;
  change: string;
  tone?: "violet" | "blue" | "green" | "red";
  icon?: ReactNode;
};

const toneStyles: Record<NonNullable<MetricCardProps["tone"]>, string> = {
  violet: "border-[var(--accent-soft)] bg-[var(--accent-soft)]",
  blue: "border-[rgba(96,165,250,0.22)] bg-[rgba(96,165,250,0.08)]",
  green: "border-[rgba(34,197,94,0.2)] bg-[rgba(34,197,94,0.08)]",
  red: "border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)]",
};

export function MetricCard({ label, value, change, tone = "violet", icon }: MetricCardProps) {
  return (
    <div className={`rounded-2xl border p-4 ${toneStyles[tone]}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="text-xs uppercase tracking-[0.08em] text-[var(--muted)]">{label}</span>
        {icon ? <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--surface)] text-[var(--text)]">{icon}</span> : null}
      </div>
      <div className="text-3xl font-semibold text-[var(--text)]">{value}</div>
      <div className="mt-2 text-xs text-[var(--secondary)]">{change}</div>
    </div>
  );
}
