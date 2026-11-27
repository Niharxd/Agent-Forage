import { apiBaseUrl } from "./config";

export type ExecutionStatus =
  | "pending"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

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

export type ExecutionPlanTask = {
  task_id: string;
  agent_type: string;
  dependency_ids: string[];
  status:
    | "pending"
    | "running"
    | "waiting_approval"
    | "completed"
    | "failed"
    | "blocked"
    | "skipped";
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
  workflow_plan?: ExecutionPlanTask[] | null;
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
  workflowId?: string;
};

export type WorkflowRecord = {
  id: string;
  name: string;
  description: string | null;
  version: number;
  workflow_definition: {
    tasks: Array<{
      task_id: string;
      agent_type?: string;
      dependency_ids?: string[];
      description?: string | null;
    }>;
  };
  created_at: string;
  updated_at: string;
  status?: "active" | "archived";
  archived_at?: string | null;
  execution_count?: number;
  last_execution_at?: string | null;
};

export type Approval = {
  approval_id: string;
  execution_id: string;
  task_id: string | null;
  tool_id: string | null;
  action_description: string;
  status: string;
  requested_at: string;
  reviewed_at: string | null;
};

export type PendingApproval = {
  approval_id: string;
  execution_id: string;
  workflow_name: string;
  task_id: string | null;
  tool_id: string | null;
  action_description: string;
  status: "pending";
  requested_at: string;
  expires_at: string;
};

export type PendingApprovalListResponse = {
  items: PendingApproval[];
  total: number;
  limit: number;
  offset: number;
};

export type PrepareResponse = { workflow: WorkflowRecord; execution: Execution };

async function request<T>(path: string, signal?: AbortSignal, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    credentials: "include",
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    signal,
    ...init,
  });

  if (!response.ok) {
    if (response.status === 401) {
      if (!signal?.aborted && typeof window !== "undefined") {
        window.dispatchEvent(new Event("agentforge:session-expired"));
      }
      throw new Error("Your session expired. Sign in again to continue.");
    }
    if (response.status === 403) throw new Error("You do not have permission to access this workspace.");
    if (response.status === 503) throw new Error("The API is temporarily unavailable or operator authentication is not configured.");
    let detail = "";
    try { const body = await response.json() as { detail?: unknown }; detail = typeof body.detail === "string" ? body.detail : ""; } catch { /* response may not contain JSON */ }
    throw new Error(detail || `Request failed (${response.status}).`);
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

export function createPlannedWorkflow(taskDescription: string, signal?: AbortSignal): Promise<PrepareResponse> {
  return request("/workflows/prepare", signal, { method: "POST", body: JSON.stringify({ task_description: taskDescription }) });
}

export function listWorkflows(
  signal?: AbortSignal,
  options: {
    limit?: number;
    offset?: number;
    sort?: "name" | "updated";
    search?: string;
    status?: "active" | "archived" | "all";
  } = {},
): Promise<{ items: WorkflowRecord[]; total: number; limit: number; offset: number }> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
    sort: options.sort ?? "name",
    status: options.status ?? "active",
  });
  if (options.search?.trim()) params.set("search", options.search.trim());
  return request(`/workflows?${params.toString()}`, signal);
}

export function getWorkflow(workflowId: string, signal?: AbortSignal): Promise<WorkflowRecord> {
  return request(`/workflows/${encodeURIComponent(workflowId)}`, signal);
}

export function updateWorkflowMetadata(
  workflowId: string,
  changes: { name?: string; description?: string | null },
): Promise<WorkflowRecord> {
  return request(`/workflows/${encodeURIComponent(workflowId)}`, undefined, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function archiveWorkflow(workflowId: string): Promise<WorkflowRecord> {
  return request(`/workflows/${encodeURIComponent(workflowId)}/archive`, undefined, {
    method: "POST",
  });
}

export function restoreWorkflow(workflowId: string): Promise<WorkflowRecord> {
  return request(`/workflows/${encodeURIComponent(workflowId)}/restore`, undefined, {
    method: "POST",
  });
}

export function listPendingApprovals(
  filters: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<PendingApprovalListResponse> {
  const params = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  return request(`/approvals?${params.toString()}`, signal);
}

export function listApprovals(executionId: string, signal?: AbortSignal): Promise<Approval[]> {
  return request(`/executions/${encodeURIComponent(executionId)}/approvals`, signal);
}

export function reviewApproval(executionId: string, approvalId: string, decision: "approve" | "reject"): Promise<Execution> {
  return request(`/executions/${encodeURIComponent(executionId)}/approvals/${encodeURIComponent(approvalId)}/${decision}`, undefined, { method: "POST" });
}

export function startExecution(executionId: string): Promise<Execution> {
  return request(`/executions/${encodeURIComponent(executionId)}/start`, undefined, { method: "POST" });
}

export function cancelExecution(executionId: string): Promise<Execution> {
  return request(`/executions/${encodeURIComponent(executionId)}/cancel`, undefined, { method: "POST" });
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
  if (filters.workflowId) {
    params.set("workflow_id", filters.workflowId);
  }
  return request(`/executions?${params.toString()}`, signal);
}

export function getExecution(executionId: string, signal?: AbortSignal): Promise<Execution> {
  return request(`/executions/${encodeURIComponent(executionId)}`, signal);
}
