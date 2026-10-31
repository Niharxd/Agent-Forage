import { Sparkles } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

type AgentCardProps = {
  name: string;
  responsibility: string;
  description: string;
  capabilities: readonly string[];
  status: string;
};

export function AgentCard({ name, responsibility, description, capabilities, status }: AgentCardProps) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[0_1px_0_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <div className="text-base font-semibold text-[var(--text)]">{name}</div>
            <div className="text-xs uppercase tracking-[0.08em] text-[var(--muted)]">{responsibility}</div>
          </div>
        </div>
        <StatusBadge tone="violet">{status}</StatusBadge>
      </div>
      <p className="text-sm leading-6 text-[var(--secondary)]">{description}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {capabilities.map((capability) => (
          <span key={capability} className="rounded-full border border-[var(--border)] bg-[var(--surface-alt)] px-2 py-1 text-[11px] text-[var(--secondary)]">
            {capability}
          </span>
        ))}
      </div>
    </div>
  );
}
