import type { ReactNode } from "react";

type BadgeTone = "violet" | "blue" | "green" | "red" | "neutral";

type StatusBadgeProps = {
  tone?: BadgeTone;
  children: ReactNode;
};

const toneClasses: Record<BadgeTone, string> = {
  violet: "bg-[var(--accent-soft)] text-[var(--accent)]",
  blue: "bg-[rgba(96,165,250,0.14)] text-[var(--info)]",
  green: "bg-[rgba(34,197,94,0.12)] text-[var(--success)]",
  red: "bg-[rgba(239,68,68,0.12)] text-[var(--error)]",
  neutral: "bg-[var(--surface-alt)] text-[var(--secondary)]",
};

export function StatusBadge({ tone = "neutral", children }: StatusBadgeProps) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-[0.02em] ${toneClasses[tone]}`}>
      {children}
    </span>
  );
}
