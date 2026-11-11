import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ExecutionsPage from "./ExecutionsPage";

const executionId = "d10f8341-d8d1-45f1-bade-a01234567890";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function executionList(items: unknown[] = [], total = items.length, offset = 0) {
  return { items, total, limit: 25, offset };
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function executionRecord(id = executionId, workflowName = "Dashboard research") {
  return {
    execution_id: id,
    workflow_name: workflowName,
    status: "completed",
    created_at: "2026-11-10T09:00:00Z",
    started_at: "2026-11-10T09:00:01Z",
    completed_at: "2026-11-10T09:00:06Z",
    task_results: {
      analyze: {
        task_id: "analyze",
        agent_type: "analyst",
        status: "completed",
        agent_result: { status: "succeeded", output: { summary: "Persisted result" } },
        tool_result: null,
        error: null,
        started_at: "2026-11-10T09:00:01Z",
        completed_at: "2026-11-10T09:00:06Z",
      },
    },
    events: [
      {
        event_type: "workflow_completed",
        execution_id: id,
        task_id: null,
        timestamp: "2026-11-10T09:00:06Z",
        from_status: "running",
        to_status: "completed",
        reason: null,
        metadata: {},
      },
    ],
    execution_order: ["analyze"],
    cancellation_requested: false,
    workflow_plan: [
      {
        task_id: "analyze",
        agent_type: "analyst",
        dependency_ids: [],
        status: "completed",
      },
    ],
  };
}

describe("ExecutionsPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads persisted executions and requests the next page", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(jsonResponse(executionList([executionRecord()], 30)));

    render(<ExecutionsPage />);

    expect(await screen.findByText("Dashboard research")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toContain("limit=25");
    expect(fetchMock.mock.calls[0][0]).toContain("offset=0");

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("offset=25"))).toBe(true);
    });
  });

  it("ignores a stale list response after a newer search response", async () => {
    const fetchMock = vi.mocked(fetch);
    const olderResponse = deferred<Response>();
    fetchMock.mockImplementation((input) =>
      String(input).includes("search=older") ? olderResponse.promise : Promise.resolve(
        jsonResponse(executionList([executionRecord(executionId, "Newer result")])),
      ),
    );
    render(<ExecutionsPage />);

    fireEvent.change(screen.getByRole("textbox", { name: "Search executions" }), {
      target: { value: "older" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByRole("textbox", { name: "Search executions" }), {
      target: { value: "newer" },
    });

    expect(await screen.findByText("Newer result")).toBeInTheDocument();
    olderResponse.resolve(jsonResponse(executionList([executionRecord(executionId, "Stale result")])));

    await waitFor(() => expect(screen.queryByText("Stale result")).not.toBeInTheDocument());
    expect(screen.getByText("Newer result")).toBeInTheDocument();
  });

  it("ignores a stale detail response after selecting another execution", async () => {
    const firstId = "first-execution";
    const secondId = "second-execution";
    const firstDetails = deferred<Response>();
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith(firstId)) {
        return firstDetails.promise;
      }
      if (url.endsWith(secondId)) {
        return Promise.resolve(jsonResponse(executionRecord(secondId, "Selected execution")));
      }
      return Promise.resolve(
        jsonResponse(
          executionList([
            executionRecord(firstId, "First execution"),
            executionRecord(secondId, "Second execution"),
          ]),
        ),
      );
    });
    render(<ExecutionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: `View execution ${firstId}` }));
    fireEvent.click(screen.getByRole("button", { name: `View execution ${secondId}` }));

    expect(await screen.findByRole("heading", { name: "Selected execution" })).toBeInTheDocument();
    firstDetails.resolve(jsonResponse(executionRecord(firstId, "Stale selected execution")));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Stale selected execution" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("heading", { name: "Selected execution" })).toBeInTheDocument();
  });

  it("recovers from an out-of-range page", async () => {
    const pageOne = deferred<Response>();
    const fetchMock = vi.mocked(fetch);
    let firstPageRequest = true;
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.includes("offset=25")) {
        return pageOne.promise;
      }
      if (firstPageRequest) {
        firstPageRequest = false;
        return Promise.resolve(
          jsonResponse(executionList([executionRecord()], 30)),
        );
      }
      return Promise.resolve(
        jsonResponse(executionList([executionRecord("recovered", "Recovered page")], 30)),
      );
    });
    render(<ExecutionsPage />);

    await screen.findByText("Dashboard research");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    pageOne.resolve(jsonResponse(executionList([], 24, 25)));

    expect(await screen.findByText("Recovered page")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("offset=0"))).toBe(true);
  });

  it("resets to the first page when all matching executions disappeared", async () => {
    const emptyPage = deferred<Response>();
    const fetchMock = vi.mocked(fetch);
    let firstPageRequest = true;
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.includes("offset=25")) {
        return emptyPage.promise;
      }
      if (firstPageRequest) {
        firstPageRequest = false;
        return Promise.resolve(
          jsonResponse(
            executionList(
              Array.from({ length: 25 }, (_, index) =>
                executionRecord(`initial-${index}`, `Initial execution ${index}`),
              ),
              26,
            ),
          ),
        );
      }
      return Promise.resolve(jsonResponse(executionList()));
    });
    render(<ExecutionsPage />);

    await screen.findByText("Initial execution 0");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    emptyPage.resolve(jsonResponse(executionList([], 0, 25)));

    expect(await screen.findByText("No executions yet")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("offset=0")).length).toBeGreaterThan(1);
  });

  it("applies search and status filters through the API", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(jsonResponse(executionList()));
    render(<ExecutionsPage />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fireEvent.change(screen.getByRole("textbox", { name: "Search executions" }), {
      target: { value: "research alpha" },
    });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).includes("search=research+alpha"),
        ),
      ).toBe(true);
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), {
      target: { value: "failed" },
    });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url]) =>
            String(url).includes("search=research+alpha") &&
            String(url).includes("status=failed"),
        ),
      ).toBe(true);
    });
  });

  it("displays task states and lifecycle events without rendering raw task output", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      return url.includes(executionId)
        ? jsonResponse(executionRecord())
        : jsonResponse(executionList([executionRecord()]));
    });
    render(<ExecutionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: `View execution ${executionId}` }));

    expect(await screen.findByRole("region", { name: `Execution details for ${executionId}` })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "analyze" })).toBeInTheDocument();
    expect(screen.getByText(/analyst · Started .* · Completed /)).toBeInTheDocument();
    expect(screen.getByText("workflow completed")).toBeInTheDocument();
    expect(screen.queryByText("Persisted result")).not.toBeInTheDocument();
  });

  it("visualizes workflow dependencies and task status from the safe plan projection", async () => {
    const fetchMock = vi.mocked(fetch);
    const record = {
      ...executionRecord(),
      workflow_plan: [
        {
          task_id: "collect",
          agent_type: "researcher",
          dependency_ids: [],
          status: "completed",
        },
        {
          task_id: "analyze",
          agent_type: "analyst",
          dependency_ids: ["collect"],
          status: "running",
        },
      ],
    };
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      return url.includes(executionId)
        ? jsonResponse(record)
        : jsonResponse(executionList([record]));
    });
    render(<ExecutionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: `View execution ${executionId}` }));

    expect(await screen.findByRole("heading", { name: "Workflow plan" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Workflow dependency graph" })).toBeInTheDocument();
    expect(screen.getByText(/Depends on: collect/)).toBeInTheDocument();
    expect(screen.getByText("researcher · completed")).toBeInTheDocument();
    expect(screen.getByText("analyst · running")).toBeInTheDocument();
    expect(screen.queryByText("Persisted result")).not.toBeInTheDocument();
  });

  it("shows a clear error and retries when the execution API is unavailable", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockRejectedValueOnce(new Error("Network unavailable"));

    render(<ExecutionsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Network unavailable");
    fetchMock.mockResolvedValueOnce(jsonResponse(executionList()));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("No executions yet")).toBeInTheDocument();
  });

  it("shows an error and retries a failed execution detail request", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementationOnce(async () => jsonResponse(executionList([executionRecord()])));
    fetchMock.mockRejectedValueOnce(new Error("Detail unavailable"));
    render(<ExecutionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: `View execution ${executionId}` }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Detail unavailable");

    fetchMock.mockResolvedValueOnce(jsonResponse(executionRecord()));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("region", { name: `Execution details for ${executionId}` })).toBeInTheDocument();
  });
});
