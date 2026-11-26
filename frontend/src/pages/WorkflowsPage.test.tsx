import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import WorkflowsPage from "./WorkflowsPage";

function response(body: unknown): Response { return { ok: true, status: 200, json: async () => body } as Response; }
const workflow = { id: "wf-1", name: "Research request", description: "Research the topic", version: 1, workflow_definition: { tasks: [{ task_id: "research" }] }, created_at: "2026-11-14T09:00:00Z", updated_at: "2026-11-14T09:00:00Z" };
const execution = { execution_id: "ex-1", workflow_name: "Research request", status: "pending", created_at: "2026-11-14T09:00:00Z", started_at: null, completed_at: null, task_results: {}, events: [], execution_order: [], cancellation_requested: false, workflow_plan: [{ task_id: "research", agent_type: "researcher", dependency_ids: [], status: "pending" }] };

describe("WorkflowsPage", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ items: [workflow], total: 1, limit: 50, offset: 0 }))));
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("loads persisted workflows and prepares a task through the real API contract", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(async (input) => String(input).includes("/workflows/prepare")
      ? response({ workflow, execution })
      : response({ items: [workflow], total: 1, limit: 50, offset: 0 }));
    render(<MemoryRouter><WorkflowsPage /></MemoryRouter>);
    expect(await screen.findByText("Research request")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/task instructions/i), { target: { value: "Research a topic" } });
    fireEvent.click(screen.getByRole("button", { name: /prepare for review/i }));
    expect(await screen.findByRole("status")).toHaveTextContent(/plan prepared and saved/i);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes("/workflows/prepare") && init?.method === "POST" && String(init.body).includes("Research a topic"))).toBe(true);
  });

  it("shows a clear API error after a failed workflow submission", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => String(input).includes("/workflows/prepare") ? Promise.reject(new Error("Planner is unavailable")) : response({ items: [], total: 0, limit: 50, offset: 0 }));
    render(<MemoryRouter><WorkflowsPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText(/task instructions/i), { target: { value: "Research a topic" } });
    fireEvent.click(screen.getByRole("button", { name: /prepare for review/i }));
    await waitFor(() => expect(screen.getAllByRole("alert")[0]).toHaveTextContent(/planner is unavailable/i));
  });

  it("opens a workflow linked from the dashboard even when it is outside the first list page", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(async (input) => String(input).endsWith(`/workflows/${workflow.id}`)
      ? response(workflow)
      : response({ items: [], total: 101, limit: 50, offset: 0 }));
    render(<MemoryRouter initialEntries={[`/workflows?workflow=${workflow.id}`]}><WorkflowsPage /></MemoryRouter>);

    expect(await screen.findByText("Research request")).toBeInTheDocument();
    expect(document.getElementById(`workflow-${workflow.id}`)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith(`/workflows/${workflow.id}`))).toBe(true);
  });
});
