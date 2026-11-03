"""Sequential deterministic workflow execution using registered agents."""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agentforge.agents import AnalystAgent, PlannerAgent, ResearcherAgent, ReviewerAgent
from agentforge.domain.agents.contracts import (
    AgentCapability,
    AgentExecutionStatus,
    AgentInput,
    AgentRole,
    PreviousAgentResult,
)
from agentforge.domain.agents.interface import Agent
from agentforge.domain.workflows.models import (
    TaskExecutionResult,
    TaskStatus,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowExecution,
    WorkflowStatus,
    WorkflowTask,
    WorkflowTaskError,
)
from agentforge.domain.workflows.validation import (
    WorkflowDefinitionInput,
    WorkflowValidator,
)

logger = logging.getLogger(__name__)

_REQUIRED_CAPABILITY = {
    AgentRole.PLANNER: AgentCapability.CREATE_PLAN,
    AgentRole.RESEARCHER: AgentCapability.RESEARCH_SUPPLIED_INFORMATION,
    AgentRole.ANALYST: AgentCapability.ANALYZE_SUPPLIED_DATA,
    AgentRole.REVIEWER: AgentCapability.REVIEW_AGAINST_CRITERIA,
}


class WorkflowEngine:
    """Validate and execute workflows in a bounded, stable, sequential order."""

    def __init__(
        self,
        agents: Mapping[AgentRole, Agent] | None = None,
        *,
        validator: WorkflowValidator | None = None,
    ) -> None:
        self._agents = dict(agents) if agents is not None else self._mock_agents()
        self._validator = validator or WorkflowValidator()
        if set(self._agents) != set(AgentRole):
            raise ValueError("The agent registry must include all four supported roles.")
        for role, agent in self._agents.items():
            if agent.identity.role != role:
                raise ValueError(
                    f"Agent registry role {role.value!r} does not match "
                    f"agent identity {agent.identity.role.value!r}."
                )

    def execute(
        self,
        definition: WorkflowDefinitionInput,
        *,
        execution_id: UUID | None = None,
    ) -> WorkflowExecution:
        """Validate and run all executable tasks, isolating task-level failures."""
        workflow, ordered_tasks = self._validator.validate_and_order(definition)
        execution = WorkflowExecution(
            execution_id=execution_id or uuid4(),
            workflow=workflow,
            task_results={
                task.task_id: TaskExecutionResult(
                    task_id=task.task_id,
                    agent_type=task.agent_type,
                    status=TaskStatus.PENDING,
                )
                for task in workflow.tasks
            },
        )
        started_at = self._now()
        execution.started_at = started_at
        execution.status = WorkflowStatus.RUNNING
        execution.events.append(
            WorkflowEvent(
                event_type=WorkflowEventType.WORKFLOW_STARTED,
                execution_id=execution.execution_id,
                timestamp=started_at,
                from_status=WorkflowStatus.PENDING.value,
                to_status=WorkflowStatus.RUNNING.value,
                metadata={"workflow_name": workflow.name, "task_count": len(workflow.tasks)},
            )
        )

        for task in ordered_tasks:
            blocked_by = [
                dependency_id
                for dependency_id in task.dependency_ids
                if execution.task_results[dependency_id].status != TaskStatus.COMPLETED
            ]
            if blocked_by:
                self._block_task(execution, task, blocked_by)
            else:
                self._run_task(execution, task)

        execution.completed_at = self._now()
        failed = any(
            result.status in {TaskStatus.FAILED, TaskStatus.BLOCKED}
            for result in execution.task_results.values()
        )
        execution.status = WorkflowStatus.FAILED if failed else WorkflowStatus.COMPLETED
        execution.events.append(
            WorkflowEvent(
                event_type=(
                    WorkflowEventType.WORKFLOW_FAILED
                    if failed
                    else WorkflowEventType.WORKFLOW_COMPLETED
                ),
                execution_id=execution.execution_id,
                timestamp=execution.completed_at,
                from_status=WorkflowStatus.RUNNING.value,
                to_status=execution.status.value,
                reason="One or more tasks failed or were blocked." if failed else None,
            )
        )
        return execution

    def _run_task(self, execution: WorkflowExecution, task: WorkflowTask) -> None:
        result = execution.task_results[task.task_id]
        result.status = TaskStatus.RUNNING
        result.started_at = self._now()
        execution.events.append(
            WorkflowEvent(
                event_type=WorkflowEventType.TASK_STARTED,
                execution_id=execution.execution_id,
                task_id=task.task_id,
                timestamp=result.started_at,
                from_status=TaskStatus.PENDING.value,
                to_status=TaskStatus.RUNNING.value,
                metadata={"agent_type": task.agent_type.value},
            )
        )

        agent = self._agents[task.agent_type]
        agent_input = self._agent_input(execution, task)
        try:
            agent_result = agent.execute(agent_input)
        except Exception as exc:
            logger.error(
                "Workflow agent raised an unexpected exception",
                extra={
                    "execution_id": str(execution.execution_id),
                    "task_id": task.task_id,
                    "exception_type": type(exc).__name__,
                },
            )
            result.status = TaskStatus.FAILED
            result.error = WorkflowTaskError(
                code="agent_exception",
                message="The registered agent raised an unexpected exception.",
                details={"exception_type": type(exc).__name__},
            )
            result.completed_at = self._now()
            self._emit_task_failure(execution, task, result)
            return

        result.agent_result = agent_result
        result.completed_at = self._now()
        if agent_result.status == AgentExecutionStatus.SUCCEEDED:
            result.status = TaskStatus.COMPLETED
            execution.events.append(
                WorkflowEvent(
                    event_type=WorkflowEventType.TASK_COMPLETED,
                    execution_id=execution.execution_id,
                    task_id=task.task_id,
                    timestamp=result.completed_at,
                    from_status=TaskStatus.RUNNING.value,
                    to_status=TaskStatus.COMPLETED.value,
                    metadata={
                        "agent_type": task.agent_type.value,
                        "execution_duration_ms": agent_result.execution_duration_ms,
                    },
                )
            )
            return

        result.status = TaskStatus.FAILED
        agent_error = agent_result.error
        if agent_error is None:
            raise RuntimeError("Failed agent results must contain a structured error.")
        result.error = WorkflowTaskError(
            code=agent_error.code.value,
            message=agent_error.message,
            details=agent_error.details,
        )
        self._emit_task_failure(execution, task, result)

    def _agent_input(
        self,
        execution: WorkflowExecution,
        task: WorkflowTask,
    ) -> AgentInput:
        prior_results: list[PreviousAgentResult] = []
        for dependency_id in sorted(task.dependency_ids):
            dependency_result = execution.task_results[dependency_id]
            dependency_agent_result = dependency_result.agent_result
            if dependency_agent_result is None:
                raise RuntimeError(f"Completed dependency {dependency_id!r} has no agent result.")
            prior_results.append(
                PreviousAgentResult(
                    agent_id=dependency_agent_result.output.agent_id,
                    status=AgentExecutionStatus.SUCCEEDED,
                    result_data=dependency_agent_result.output.result_data,
                    summary=dependency_agent_result.output.summary,
                )
            )

        return AgentInput(
            task_description=task.description or task.task_id,
            execution_context={
                "execution_id": str(execution.execution_id),
                "workflow_name": execution.workflow.name,
                "task_id": task.task_id,
            },
            input_data=task.input_data,
            previous_results=prior_results,
            requested_capabilities=frozenset({_REQUIRED_CAPABILITY[task.agent_type]}),
            review_criteria=task.review_criteria,
        )

    def _block_task(
        self,
        execution: WorkflowExecution,
        task: WorkflowTask,
        blocked_by: list[str],
    ) -> None:
        result = execution.task_results[task.task_id]
        result.status = TaskStatus.BLOCKED
        result.completed_at = self._now()
        result.error = WorkflowTaskError(
            code="dependency_failed",
            message="Task was not run because one or more dependencies did not complete.",
            details={"blocked_by": blocked_by},
        )
        execution.events.append(
            WorkflowEvent(
                event_type=WorkflowEventType.TASK_BLOCKED,
                execution_id=execution.execution_id,
                task_id=task.task_id,
                timestamp=result.completed_at,
                from_status=TaskStatus.PENDING.value,
                to_status=TaskStatus.BLOCKED.value,
                reason=result.error.message,
                metadata={"blocked_by": blocked_by},
            )
        )

    def _emit_task_failure(
        self,
        execution: WorkflowExecution,
        task: WorkflowTask,
        result: TaskExecutionResult,
    ) -> None:
        if result.error is None:
            raise RuntimeError("Failed tasks must contain a structured error.")
        execution.events.append(
            WorkflowEvent(
                event_type=WorkflowEventType.TASK_FAILED,
                execution_id=execution.execution_id,
                task_id=task.task_id,
                timestamp=result.completed_at or self._now(),
                from_status=TaskStatus.RUNNING.value,
                to_status=TaskStatus.FAILED.value,
                reason=result.error.message,
                metadata={
                    "agent_type": task.agent_type.value,
                    "error": result.error.model_dump(mode="json"),
                },
            )
        )

    @staticmethod
    def _mock_agents() -> dict[AgentRole, Agent]:
        agents: tuple[Agent, ...] = (
            PlannerAgent(),
            ResearcherAgent(),
            AnalystAgent(),
            ReviewerAgent(),
        )
        return {agent.identity.role: agent for agent in agents}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)


__all__ = ["WorkflowEngine"]
