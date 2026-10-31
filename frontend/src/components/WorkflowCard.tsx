import { ArrowUpRight } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

type WorkflowCardProps = {
  name: string;
  description: string;
  updated: string;
  status: string;
  executionCount: number;
};

export function WorkflowCard({ name, description, updated, status, executionCount }: WorkflowCardProps) {
  const badgeTone = status === "Running" ? "violet" : status === "Completed" ? "green" : status === "Queued" ? "blue" : "neutral";

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
            <span>{name}</span>
            <ArrowUpRight className="h-3.5 w-3.5 text-[var(--muted)]" />
          </div>
          <p className="mt-1 text-sm text-[var(--secondary)]">{description}</p>
        </div>
        <StatusBadge tone={badgeTone}>{status}</StatusBadge>
      </div>
      <div className="mt-4 flex items-center justify-between text-xs text-[var(--secondary)]">
        <span>Updated {updated}</span>
        <span>{executionCount} runs</span>
      </div>
    </div>
  );
}
