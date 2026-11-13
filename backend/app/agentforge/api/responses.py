"""Safe API response projections for workflow execution state."""

from agentforge.api.schemas import ExecutionPlanTask, ExecutionResponse
from agentforge.domain.workflows.models import (
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionSnapshot,
)


def execution_response(
    execution: WorkflowExecution | WorkflowExecutionSnapshot,
    workflow_definition: WorkflowDefinition | None = None,
) -> ExecutionResponse:
    """Convert an execution snapshot to its public response contract."""
    snapshot = execution.snapshot() if isinstance(execution, WorkflowExecution) else execution
    response_data = snapshot.model_dump(mode="python")
    if workflow_definition is not None:
        response_data["workflow_plan"] = [
            ExecutionPlanTask(
                task_id=task.task_id,
                agent_type=task.agent_type,
                dependency_ids=task.dependency_ids,
                status=snapshot.task_results[task.task_id].status,
            ).model_dump(mode="python")
            for task in workflow_definition.tasks
        ]
    return ExecutionResponse.model_validate(response_data)
