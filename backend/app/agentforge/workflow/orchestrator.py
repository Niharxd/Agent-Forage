"""Coordinate draft planning, validated workflow preparation, and explicit start."""

from collections.abc import Callable, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from agentforge.agents.planner import PlannerResult
from agentforge.domain.agents.contracts import (
    AgentCapability,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentInput,
    AgentRole,
    JsonObject,
)
from agentforge.domain.agents.interface import Agent
from agentforge.domain.workflows.models import (
    MAX_WORKFLOW_DESCRIPTION_LENGTH,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionSnapshot,
    WorkflowTask,
)
from agentforge.workflow.engine import ExecutionUpdateCallback, WorkflowEngine


class WorkflowOrchestrationError(RuntimeError):
    """Safe, categorized failure while preparing an agent-proposed workflow."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PreparedWorkflow(BaseModel):
    """Validated planner output and its pending, not-yet-started execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    planner_result: AgentExecutionResult
    workflow: WorkflowDefinition
    execution: WorkflowExecutionSnapshot


PreparedWorkflowCallback = Callable[[WorkflowDefinition, WorkflowExecutionSnapshot], None]


class WorkflowOrchestrator:
    """Translate a Planner draft into a validated workflow that awaits explicit start."""

    def __init__(
        self,
        engine: WorkflowEngine | None = None,
        *,
        planner: Agent | None = None,
    ) -> None:
        self.engine = engine if engine is not None else WorkflowEngine()
        self._planner = planner if planner is not None else self.engine.planner
        if self._planner.identity.role != AgentRole.PLANNER:
            raise ValueError("The orchestration planner must implement the planner role.")

    def prepare(
        self,
        task_description: str,
        *,
        input_data: JsonObject | None = None,
        review_criteria: Sequence[str] = (),
        on_prepared: PreparedWorkflowCallback | None = None,
    ) -> PreparedWorkflow:
        """Plan, validate, and register pending work without executing workflow tasks."""
        planner_result = self._planner.execute(
            AgentInput(
                task_description=task_description,
                input_data=input_data or {},
                requested_capabilities=frozenset({AgentCapability.CREATE_PLAN}),
            )
        )
        if planner_result.status != AgentExecutionStatus.SUCCEEDED:
            raise WorkflowOrchestrationError(
                "planning_failed",
                "The planner could not produce a workflow draft.",
            )

        try:
            draft = PlannerResult.model_validate(planner_result.output.result_data)
        except ValidationError as exc:
            raise WorkflowOrchestrationError(
                "invalid_planner_output",
                "The planner returned an invalid workflow draft.",
            ) from exc
        if draft.plan_status != "draft_only":
            raise WorkflowOrchestrationError(
                "invalid_planner_status",
                "The planner output was not marked as a non-executable draft.",
            )

        tasks: list[WorkflowTask] = []
        for proposed_step in draft.proposed_steps:
            dependencies = [tasks[-1].task_id] if tasks else []
            tasks.append(
                WorkflowTask(
                    task_id=proposed_step.step_id,
                    agent_type=proposed_step.assigned_role,
                    input_data=input_data or {},
                    dependency_ids=dependencies,
                    description=proposed_step.instruction,
                )
            )

        normalized_criteria = list(review_criteria)
        if normalized_criteria:
            used_ids = {task.task_id for task in tasks}
            review_id = "final_review"
            suffix = 2
            while review_id in used_ids:
                review_id = f"final_review_{suffix}"
                suffix += 1
            tasks.append(
                WorkflowTask(
                    task_id=review_id,
                    agent_type="reviewer",
                    input_data={"request": task_description},
                    dependency_ids=[task.task_id for task in tasks],
                    description="Review the completed workflow against the supplied criteria.",
                    review_criteria=normalized_criteria,
                )
            )

        workflow = WorkflowDefinition(
            name="planner-proposed workflow",
            description=_bounded_objective(draft.objective),
            tasks=tasks,
        )
        on_update: ExecutionUpdateCallback | None = None
        if on_prepared is not None:

            def persist_initial_snapshot(snapshot: WorkflowExecutionSnapshot) -> None:
                on_prepared(workflow, snapshot)

            on_update = persist_initial_snapshot
        execution = self.engine.create_execution(workflow, on_update=on_update)
        return PreparedWorkflow(
            planner_result=planner_result,
            workflow=workflow,
            execution=execution,
        )

    def start(
        self,
        execution_id: UUID,
        *,
        on_update: ExecutionUpdateCallback | None = None,
    ) -> WorkflowExecution:
        """Explicitly start a pending workflow through the bounded workflow engine."""
        return self.engine.run(execution_id, on_update=on_update)

    def cancel(
        self,
        execution_id: UUID,
        *,
        on_update: ExecutionUpdateCallback | None = None,
    ) -> WorkflowExecutionSnapshot:
        """Delegate cancellation to the workflow engine's lifecycle controls."""
        return self.engine.cancel(execution_id, on_update=on_update)


def _bounded_objective(objective: str) -> str:
    """Keep long planner objectives visibly abbreviated within workflow metadata bounds."""
    if len(objective) <= MAX_WORKFLOW_DESCRIPTION_LENGTH:
        return objective
    return f"{objective[: MAX_WORKFLOW_DESCRIPTION_LENGTH - 3].rstrip()}..."
