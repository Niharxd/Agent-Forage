import { Activity, ArrowRight, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { dashboardMetrics, dashboardStateLabel, executionActivity, quickAccessCards, recentWorkflows } from "../data/demoData";

type DemoState = "live" | "empty" | "error" | "loading";

export default function DashboardPage() {
  const [demoState, setDemoState] = useState<DemoState>("live");

  useEffect(() => {
    if (demoState !== "loading") {
      return undefined;
    }

    const timer = window.setTimeout(() => setDemoState("live"), 700);
    return () => window.clearTimeout(timer);
  }, [demoState]);

  const isEmpty = demoState === "empty";

  if (demoState === "loading") {
    return <LoadingState label="Preparing dashboard demo" />;
  }

  if (demoState === "error") {
    return <ErrorState onRetry={() => setDemoState("live")} description="Demo dashboard content failed to load. Retry the mock view to continue." />;
  }

  return (
    <div>
      <section className="mb-6 rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5 md:p-7">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface-alt)] px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--muted)]">
              <Sparkles className="h-3.5 w-3.5" />
              Demo data only
            </div>
            <h1 className="text-3xl font-semibold tracking-[-0.05em] text-[var(--text)]">
              Welcome back, Nihar.
            </h1>
            <p className="mt-2 max-w-xl text-sm text-[var(--secondary)]">
              AgentForge keeps your AI workflows visible, coordinated, and ready for review across execution and delivery.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary">View workflow queue</Button>
            <Button>Create Workflow</Button>
          </div>
        </div>
      </section>

      <div className="mb-5 flex flex-wrap gap-2">
        {(["live", "empty", "error", "loading"] as const).map((state) => (
          <button
            key={state}
            type="button"
            onClick={() => setDemoState(state)}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              demoState === state
                ? "border-[var(--primary)] bg-[var(--accent-soft)] text-[var(--accent)]"
                : "border-[var(--border)] bg-[var(--surface)] text-[var(--secondary)] hover:text-[var(--text)]"
            }`}
          >
            {dashboardStateLabel[state]}
          </button>
        ))}
      </div>

      {isEmpty ? (
        <EmptyState
          title="No workflows to display"
          description="This dashboard is intentionally empty to demonstrate the empty state before real data is connected."
          action={<Button>Start a workflow</Button>}
        />
      ) : (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {dashboardMetrics.map((metric) => (
              <MetricCard
                key={metric.label}
                label={metric.label}
                value={metric.value}
                change={metric.change}
                tone={metric.tone as "violet" | "blue" | "green" | "red"}
                icon={<Activity className="h-4 w-4" />}
              />
            ))}
          </section>

          <section className="mt-6 grid gap-6 xl:grid-cols-[1.5fr_1fr]">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-[var(--text)]">Recent workflows</h2>
                  <div className="mt-1 text-xs text-[var(--muted)]">Development demo entries</div>
                </div>
                <Button variant="ghost" size="sm">View all</Button>
              </div>

              <div className="space-y-3">
                {recentWorkflows.map((workflow) => (
                  <div key={workflow.name} className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface-alt)] p-3">
                    <div>
                      <div className="font-medium text-[var(--text)]">{workflow.name}</div>
                      <div className="mt-1 text-xs text-[var(--secondary)]">{workflow.description}</div>
                    </div>
                    <div className="flex items-center gap-3 text-right">
                      <div className="text-xs text-[var(--secondary)]">{workflow.updated}</div>
                      <StatusBadge tone={workflow.status === "Running" ? "violet" : workflow.status === "Completed" ? "green" : workflow.status === "Queued" ? "blue" : "neutral"}>
                        {workflow.status}
                      </StatusBadge>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-[var(--text)]">Execution activity</h2>
                  <div className="mt-1 text-xs text-[var(--muted)]">Recent operational signals</div>
                </div>
                <ArrowRight className="h-4 w-4 text-[var(--muted)]" />
              </div>

              <div className="space-y-3">
                {executionActivity.map((item) => (
                  <div key={`${item.workflow}-${item.time}`} className="rounded-xl border border-[var(--border)] bg-[var(--surface-alt)] p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-[var(--text)]">{item.workflow}</div>
                      <StatusBadge tone={item.status === "Succeeded" ? "green" : item.status === "Running" ? "violet" : item.status === "Failed" ? "red" : "blue"}>
                        {item.status}
                      </StatusBadge>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-xs text-[var(--secondary)]">
                      <span>{item.time}</span>
                      <span>{item.duration}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-[var(--text)]">Quick access</h2>
                <div className="mt-1 text-xs text-[var(--muted)]">Agent and tooling shortcuts</div>
              </div>
              <Button variant="secondary" size="sm">
                Manage shortcuts
              </Button>
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {quickAccessCards.map((quickAccess) => {
                const Icon = quickAccess.icon;
                return (
                  <div key={quickAccess.name} className="rounded-xl border border-[var(--border)] bg-[var(--surface-alt)] p-4">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]">
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="mt-4 text-sm font-semibold text-[var(--text)]">{quickAccess.name}</div>
                    <p className="mt-2 text-xs leading-5 text-[var(--secondary)]">{quickAccess.description}</p>
                  </div>
                );
              })}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
