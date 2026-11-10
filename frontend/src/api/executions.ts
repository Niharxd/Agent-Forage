export type ExecutionStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export type ExecutionTaskResult = {
  task_id: string;
  agent_type: string;
  status: string;
  agent_result: unknown | null;
  tool_result: unknown | null;
  error: {
    code: string;
    message: string;
    occurred_at: string;
  } | null;
  started_at: string | null;
  completed_at: string | null;
};

export type ExecutionEvent = {
  event_type: string;
  execution_id: string;
  task_id: string | null;
  timestamp: string;
  from_status: string | null;
  to_status: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
};

export type Execution = {
  execution_id: string;
  workflow_name: string;
  status: ExecutionStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  task_results: Record<string, ExecutionTaskResult>;
  events: ExecutionEvent[];
  execution_order: string[];
  cancellation_requested: boolean;
};

export type ExecutionListResponse = {
  items: Execution[];
  total: number;
  limit: number;
  offset: number;
};

export type ExecutionListFilters = {
  limit: number;
  offset: number;
  status: ExecutionStatus | undefined;
  search: string;
};

const apiBaseUrl = "/api/v1";

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Request failed (${response.status}).`);
  }

  try {
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error("The server returned an invalid response.");
    }
    throw error;
  }
}

export function listExecutions(
  filters: ExecutionListFilters,
  signal?: AbortSignal,
): Promise<ExecutionListResponse> {
  const params = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.search.trim()) {
    params.set("search", filters.search.trim());
  }
  return request(`/executions?${params.toString()}`, signal);
}

export function getExecution(executionId: string, signal?: AbortSignal): Promise<Execution> {
  return request(`/executions/${encodeURIComponent(executionId)}`, signal);
}
