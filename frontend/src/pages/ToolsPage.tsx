import { Plus } from "lucide-react";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { toolRegistry } from "../data/demoData";

export default function ToolsPage() {
  const hasTools = toolRegistry.length > 0;

  return (
    <div>
      <PageHeader
        title="Tools"
        description="Development registry entries for the workflow platform."
        actions={<Button><Plus className="mr-2 h-4 w-4" />Register tool</Button>}
      />

      {hasTools ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {toolRegistry.map((tool) => (
            <div key={tool.name} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-[var(--text)]">{tool.name}</div>
                  <div className="mt-1 text-xs uppercase tracking-[0.08em] text-[var(--muted)]">{tool.category}</div>
                </div>
                <StatusBadge tone={tool.status === "Available" ? "green" : tool.status === "Preview" ? "blue" : "neutral"}>{tool.status}</StatusBadge>
              </div>
              <p className="mt-4 text-sm leading-6 text-[var(--secondary)]">{tool.description}</p>
              <div className="mt-4 flex items-center justify-between text-xs text-[var(--secondary)]">
                <span>Permission</span>
                <span className="font-medium text-[var(--text)]">{tool.permission}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No tools registered yet"
          description="The registry is currently a software demo placeholder until backend integrations are live."
        />
      )}
    </div>
  );
}
