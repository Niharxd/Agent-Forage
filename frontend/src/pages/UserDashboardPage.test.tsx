import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import UserDashboardPage from "./UserDashboardPage";

function response(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const workflow = {
  id: "workflow-1",
  name: "Research workspace",
  description: "A saved research workflow",
  version: 2,
  workflow_definition: { tasks: [{ task_id: "research" }] },
  created_at: "2026-11-20T09:00:00Z",
  updated_at: "2026-11-25T10:00:00Z",
};

const execution = {
  execution_id: "execution-1",
  workflow_name: "Research workspace",
  status: "completed",
  created_at: "2026-11-25T09:00:00Z",
  started_at: "2026-11-25T09:00:01Z",
  completed_at: "2026-11-25T09:00:11Z",
  task_results: {},
  events: [],
  execution_order: [],
  cancellation_requested: false,
};

const approval = {
  approval_id: "approval-1",
  execution_id: "execution-2",
  workflow_name: "Review workflow",
  task_id: "review",
  tool_id: "web_search",
  action_description: "Search the approved public sources.",
  status: "pending",
  requested_at: "2026-11-25T08:30:00Z",
  expires_at: "2026-11-26T08:30:00Z",
};

function dashboardFetch({
  workflows = [workflow],
  workflowTotal = workflows.length,
  executions = [execution],
  executionTotal = executions.length,
  completedTotal = 4,
  failedTotal = 1,
  approvals = [approval],
  approvalTotal = approvals.length,
  failWorkflows = false,
}: {
  workflows?: typeof workflow[];
  workflowTotal?: number;
  executions?: typeof execution[];
  executionTotal?: number;
  completedTotal?: number;
  failedTotal?: number;
  approvals?: typeof approval[];
  approvalTotal?: number;
  failWorkflows?: boolean;
} = {}) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/workflows")) {
      if (failWorkflows) return Promise.resolve(response({ detail: "Workflow lookup failed" }, 503));
      return Promise.resolve(response({ items: workflows, total: workflowTotal, limit: 5, offset: 0 }));
    }
    if (url.pathname.endsWith("/executions")) {
      const status = url.searchParams.get("status");
      const total = status === "completed" ? completedTotal : status === "failed" ? failedTotal : executionTotal;
      const items = status ? [] : executions;
      return Promise.resolve(response({ items, total, limit: status ? 1 : 8, offset: 0 }));
    }
    if (url.pathname.endsWith("/approvals")) {
      return Promise.resolve(response({ items: approvals, total: approvalTotal, limit: 5, offset: 0 }));
    }
    return Promise.reject(new Error(`Unexpected request: ${url.pathname}`));
  });
}

describe("UserDashboardPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", dashboardFetch());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders workspace metrics, recent execution, pending approval, and updated workflows", async () => {
    vi.stubGlobal("fetch", dashboardFetch({ executionTotal: 9 }));
    render(<MemoryRouter><UserDashboardPage /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: /welcome back/i })).toBeInTheDocument();
    expect(screen.getAllByText("Research workspace")).toHaveLength(2);
    expect(screen.getByText("Review workflow")).toBeInTheDocument();
    expect(screen.getByText("Search the approved public sources.")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("10s")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /review/i })).toHaveAttribute(
      "href",
      "/executions?execution=execution-2",
    );
    expect(screen.getAllByRole("link", { name: /research workspace/i }).some((link) =>
      link.getAttribute("href") === "/workflows?workflow=workflow-1",
    )).toBe(true);
  });

  it("shows loading states while workspace requests are pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    render(<MemoryRouter><UserDashboardPage /></MemoryRouter>);

    expect(screen.getByRole("status", { name: /loading recent executions/i })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /loading pending approvals/i })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /loading workflows/i })).toBeInTheDocument();
  });

  it("shows deliberate empty states when the workspace has no records", async () => {
    vi.stubGlobal("fetch", dashboardFetch({
      workflows: [],
      executions: [],
      approvals: [],
      executionTotal: 0,
      completedTotal: 0,
      failedTotal: 0,
      approvalTotal: 0,
    }));
    render(<MemoryRouter><UserDashboardPage /></MemoryRouter>);

    expect(await screen.findByText("Your activity will appear here")).toBeInTheDocument();
    expect(screen.getByText("Nothing needs your attention")).toBeInTheDocument();
    expect(screen.getByText("Start with your first workflow")).toBeInTheDocument();
  });

  it("keeps other dashboard sections available when one API fails", async () => {
    vi.stubGlobal("fetch", dashboardFetch({ failWorkflows: true, executionTotal: 9 }));
    render(<MemoryRouter><UserDashboardPage /></MemoryRouter>);

    expect(await screen.findByRole("alert")).toHaveTextContent(/temporarily unavailable/i);
    expect(screen.getByText("Research workspace")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Review workflow")).toBeInTheDocument());
  });
});
