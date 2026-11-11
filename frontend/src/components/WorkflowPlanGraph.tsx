import type { ExecutionPlanTask } from "../api/executions";

const NODE_WIDTH = 184;
const NODE_HEIGHT = 72;
const COLUMN_GAP = 88;
const ROW_GAP = 32;
const PADDING = 24;

function taskDepth(
  taskId: string,
  tasksById: Map<string, ExecutionPlanTask>,
  depths: Map<string, number>,
  visiting = new Set<string>(),
): number {
  const cachedDepth = depths.get(taskId);
  if (cachedDepth !== undefined) {
    return cachedDepth;
  }
  if (visiting.has(taskId)) {
    return 0;
  }

  const task = tasksById.get(taskId);
  if (!task) {
    return 0;
  }
  const nextVisiting = new Set(visiting).add(taskId);
  const depth = task.dependency_ids.reduce(
    (maximum, dependencyId) =>
      Math.max(maximum, taskDepth(dependencyId, tasksById, depths, nextVisiting) + 1),
    0,
  );
  depths.set(taskId, depth);
  return depth;
}

function statusColor(status: ExecutionPlanTask["status"]): string {
  switch (status) {
    case "completed":
      return "var(--success)";
    case "failed":
      return "var(--error)";
    case "running":
      return "var(--accent)";
    case "pending":
    case "blocked":
    case "skipped":
      return "var(--border)";
  }
}

export function WorkflowPlanGraph({ tasks }: { tasks: ExecutionPlanTask[] }) {
  const tasksById = new Map(tasks.map((task) => [task.task_id, task]));
  const depths = new Map<string, number>();
  const columns = new Map<number, ExecutionPlanTask[]>();

  for (const task of tasks) {
    const depth = taskDepth(task.task_id, tasksById, depths);
    columns.set(depth, [...(columns.get(depth) ?? []), task]);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [depth, columnTasks] of columns) {
    columnTasks.forEach((task, row) => {
      positions.set(task.task_id, {
        x: PADDING + depth * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING + row * (NODE_HEIGHT + ROW_GAP),
      });
    });
  }

  const maximumDepth = Math.max(0, ...columns.keys());
  const columnCount = maximumDepth + 1;
  const rowCount = Math.max(1, ...Array.from(columns.values(), (column) => column.length));
  const width = PADDING * 2 + columnCount * NODE_WIDTH + (columnCount - 1) * COLUMN_GAP;
  const height = PADDING * 2 + rowCount * NODE_HEIGHT + (rowCount - 1) * ROW_GAP;

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--surface-alt)] p-2">
        <svg
          role="img"
          aria-label="Workflow dependency graph"
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          className="max-w-none"
        >
          {tasks.flatMap((task) =>
            task.dependency_ids.flatMap((dependencyId) => {
              const from = positions.get(dependencyId);
              const to = positions.get(task.task_id);
              if (!from || !to) {
                return [];
              }
              const startX = from.x + NODE_WIDTH;
              const startY = from.y + NODE_HEIGHT / 2;
              const endX = to.x;
              const endY = to.y + NODE_HEIGHT / 2;
              const controlX = (startX + endX) / 2;
              return [
                <path
                  key={`${dependencyId}-${task.task_id}`}
                  d={`M ${startX} ${startY} C ${controlX} ${startY}, ${controlX} ${endY}, ${endX} ${endY}`}
                  fill="none"
                  stroke="var(--muted)"
                  strokeWidth="2"
                  markerEnd="url(#workflow-arrow)"
                />,
              ];
            }),
          )}
          <defs>
            <marker
              id="workflow-arrow"
              markerWidth="8"
              markerHeight="8"
              refX="6"
              refY="3"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 6 3 L 0 6 z" fill="var(--muted)" />
            </marker>
          </defs>
          {tasks.map((task) => {
            const position = positions.get(task.task_id);
            if (!position) {
              return null;
            }
            const label =
              task.task_id.length > 23 ? `${task.task_id.slice(0, 20)}...` : task.task_id;
            return (
              <g key={task.task_id}>
                <title>{`${task.task_id}: ${task.agent_type}, ${task.status}`}</title>
                <rect
                  x={position.x}
                  y={position.y}
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx="12"
                  fill="var(--surface)"
                  stroke={statusColor(task.status)}
                  strokeWidth="2"
                />
                <text
                  x={position.x + 12}
                  y={position.y + 25}
                  fill="var(--text)"
                  fontSize="13"
                  fontWeight="600"
                >
                  {label}
                </text>
                <text
                  x={position.x + 12}
                  y={position.y + 47}
                  fill="var(--secondary)"
                  fontSize="12"
                >
                  {task.agent_type} · {task.status}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <ol className="space-y-2 text-sm text-[var(--secondary)]">
        {tasks.map((task) => (
          <li key={task.task_id}>
            <span className="font-medium text-[var(--text)]">{task.task_id}</span>
            {" — "}
            {task.agent_type} · {task.status}
            {task.dependency_ids.length > 0
              ? ` · Depends on: ${task.dependency_ids.join(", ")}`
              : " · No dependencies"}
          </li>
        ))}
      </ol>
    </div>
  );
}
