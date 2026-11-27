import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

  it("searches, filters, sorts, and paginates workflows through the API", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(response({ items: [workflow], total: 40, limit: 25, offset: 0 }));
    render(<MemoryRouter><WorkflowsPage /></MemoryRouter>);

    expect(await screen.findByText("Research request")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search workflows" }), {
      target: { value: "topic" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), {
      target: { value: "archived" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Sort by" }), {
      target: { value: "name" },
    });

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) =>
        String(url).includes("search=topic")
        && String(url).includes("status=archived")
        && String(url).includes("sort=name"),
      )).toBe(true);
    });
    fireEvent.click(await screen.findByRole("button", { name: "Next" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("offset=25"))).toBe(true);
    });
  });

  it("shows loading, empty, error, and retry states for the workflow registry", async () => {
    let resolveList!: (value: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveList = resolve; }));
    render(<MemoryRouter><WorkflowsPage /></MemoryRouter>);
    expect(screen.getByRole("status", { name: "Loading workflows" })).toBeInTheDocument();
    resolveList(response({ items: [], total: 0, limit: 25, offset: 0 }));
    expect(await screen.findByText("No saved workflows yet")).toBeInTheDocument();

    cleanup();
    vi.mocked(fetch).mockRejectedValueOnce(new Error("Workflow API unavailable"));
    render(<MemoryRouter><WorkflowsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Workflow API unavailable"));
    vi.mocked(fetch).mockResolvedValueOnce(response({ items: [], total: 0, limit: 25, offset: 0 }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No saved workflows yet")).toBeInTheDocument();
  });

  it("shows workflow metadata, planned steps, and associated execution history", async () => {
    const fetchMock = vi.mocked(fetch);
    const detailedWorkflow = {
      ...workflow,
      workflow_definition: {
        tasks: [{
          task_id: "research",
          agent_type: "researcher",
          dependency_ids: [],
          description: "Collect the source material.",
        }],
      },
      execution_count: 1,
    };
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith(`/workflows/${workflow.id}`)) return response(detailedWorkflow);
      if (url.includes("/executions?")) {
        return response({ items: [execution], total: 1, limit: 5, offset: 0 });
      }
      return response({ items: [], total: 0, limit: 25, offset: 0 });
    });
    render(
      <MemoryRouter initialEntries={[`/workflows/${workflow.id}`]}>
        <Routes><Route path="/workflows/:workflowId" element={<WorkflowsPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Workflow plan" })).toBeInTheDocument();
    expect(screen.getByText("Collect the source material.")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Workflow dependency graph" })).toBeInTheDocument();
    expect(await screen.findByText("ex-1")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) =>
      String(url).includes(`workflow_id=${workflow.id}`),
    )).toBe(true);
  });

  it("edits metadata without sending ownership or workflow-definition fields", async () => {
    const fetchMock = vi.mocked(fetch);
    const detailedWorkflow = {
      ...workflow,
      workflow_definition: { tasks: [{ task_id: "research", agent_type: "researcher" }] },
    };
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).includes("/executions?")) {
        return response({ items: [], total: 0, limit: 5, offset: 0 });
      }
      if (init?.method === "PATCH") return response({ ...detailedWorkflow, name: "Updated research" });
      return response(detailedWorkflow);
    });
    render(
      <MemoryRouter initialEntries={[`/workflows/${workflow.id}`]}>
        <Routes><Route path="/workflows/:workflowId" element={<WorkflowsPage />} /></Routes>
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Updated research" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Updated details" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("status")).toHaveTextContent(/definition and execution history are unchanged/i);
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(patchCall).toBeDefined();
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({
      name: "Updated research",
      description: "Updated details",
    });
    expect(screen.getByRole("img", { name: "Workflow dependency graph" })).toBeInTheDocument();
  });

  it("confirms archive and restore actions", async () => {
    const fetchMock = vi.mocked(fetch);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).includes("/executions?")) {
        return response({ items: [], total: 0, limit: 5, offset: 0 });
      }
      if (String(input).endsWith("/archive") && init?.method === "POST") {
        return response({ ...workflow, status: "archived", archived_at: "2026-11-20T09:00:00Z" });
      }
      if (String(input).endsWith("/restore") && init?.method === "POST") {
        return response({ ...workflow, status: "active", archived_at: null });
      }
      return response(workflow);
    });
    render(
      <MemoryRouter initialEntries={[`/workflows/${workflow.id}`]}>
        <Routes><Route path="/workflows/:workflowId" element={<WorkflowsPage />} /></Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Archive workflow" }));
    expect(await screen.findByText("Workflow archived.")).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledWith(
      "Archive this workflow? Its definition and execution history will be retained.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Restore workflow" }));
    expect(await screen.findByText("Workflow restored.")).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(2);
  });
});
