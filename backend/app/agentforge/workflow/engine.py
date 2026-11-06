"""Sequential deterministic workflow execution using registered agents."""

import json
import logging
from collections import OrderedDict
from collections.abc import Mapping
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from agentforge.agents import AnalystAgent, PlannerAgent, ResearcherAgent, ReviewerAgent
from agentforge.config.settings import Settings
from agentforge.domain.agents.contracts import (
    AgentCapability,
    AgentErrorCode,
    AgentExecutionResult,
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
    WorkflowExecutionSnapshot,
    WorkflowStatus,
    WorkflowTask,
    WorkflowTaskError,
)
from agentforge.domain.workflows.validation import (
    WorkflowDefinitionInput,
    WorkflowValidationError,
    WorkflowValidationIssue,
    WorkflowValidator,
)
from agentforge.tools import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolExecutor,
)

logger = logging.getLogger(__name__)

_REQUIRED_CAPABILITY = {
    AgentRole.PLANNER: AgentCapability.CREATE_PLAN,
    AgentRole.RESEARCHER: AgentCapability.RESEARCH_SUPPLIED_INFORMATION,
    AgentRole.ANALYST: AgentCapability.ANALYZE_SUPPLIED_DATA,
    AgentRole.REVIEWER: AgentCapability.REVIEW_AGAINST_CRITERIA,
}

_SAFE_AGENT_ERROR_MESSAGES = {
    AgentErrorCode.INVALID_INPUT: "The agent rejected invalid input.",
    AgentErrorCode.UNSUPPORTED_CAPABILITY: "The agent does not support a requested capability.",
    AgentErrorCode.EXECUTION_FAILURE: "The agent could not complete the task.",
    AgentErrorCode.TIMEOUT: "The agent execution timed out.",
    AgentErrorCode.VALIDATION_FAILURE: "The agent returned an invalid result.",
    AgentErrorCode.INTERNAL_AGENT_ERROR: "The agent encountered an internal error.",
}


class ExecutionNotFoundError(LookupError):
    """Raised when an execution ID is absent from both active state and history."""


class InvalidExecutionStateError(ValueError):
    """Raised when an operation is not valid for the current execution state."""


class WorkflowEngine:
    """Validate and execute workflows in a bounded, stable, sequential order."""

    def __init__(
        self,
        agents: Mapping[AgentRole, Agent] | None = None,
        *,
        validator: WorkflowValidator | None = None,
        settings: Settings | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        settings = settings or Settings()
        self._agents = dict(agents) if agents is not None else self._mock_agents()
        self._validator = validator or WorkflowValidator(
            max_tasks=settings.workflow_max_tasks,
            max_task_input_bytes=settings.workflow_max_task_input_bytes,
        )
        self._max_execution_steps = settings.workflow_max_execution_steps
        self._max_result_bytes = settings.workflow_max_result_bytes
        self._max_history_size = settings.workflow_history_size
        self._tool_executor = tool_executor or ToolExecutor()
        if set(self._agents) != set(AgentRole):
            raise ValueError("The agent registry must include all four supported roles.")
        for role, agent in self._agents.items():
            if agent.identity.role != role:
                raise ValueError(
                    f"Agent registry role {role.value!r} does not match "
                    f"agent identity {agent.identity.role.value!r}."
                )

        self._lock = RLock()
        self._active: dict[UUID, WorkflowExecution] = {}
        self._history: OrderedDict[UUID, WorkflowExecutionSnapshot] = OrderedDict()

    def create_execution(
        self,
        definition: WorkflowDefinitionInput,
        *,
        execution_id: UUID | None = None,
    ) -> WorkflowExecutionSnapshot:
        """Validate and register a pending execution without dispatching an agent."""
        workflow, _ = self._validator.validate_and_order(definition)
        tool_issues: list[WorkflowValidationIssue] = []
        for task in workflow.tasks:
            if task.tool_request is None:
                continue
            agent = self._agents[task.agent_type]
            request = ToolExecutionRequest(
                tool_id=task.tool_request.tool_id,
                agent_id=agent.identity.agent_id,
                arguments=task.tool_request.arguments,
                agent_capabilities=agent.supported_capabilities,
            )
            try:
                self._tool_executor.validate_request(
                    request,
                    agent_capabilities=agent.supported_capabilities,
                )
            except (TypeError, ValueError):
                tool_issues.append(
                    WorkflowValidationIssue(
                        code="unsafe_tool_request",
                        message=(
                            f"Task {task.task_id!r} has an invalid or unauthorized tool request."
                        ),
                        task_id=task.task_id,
                        location=("tasks", task.task_id, "tool_request"),
                    )
                )
        if tool_issues:
            raise WorkflowValidationError(tool_issues)
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
        with self._lock:
            if execution.execution_id in self._active or execution.execution_id in self._history:
                raise ValueError(f"Execution ID {execution.execution_id} is already in use.")
            self._active[execution.execution_id] = execution
            return execution.snapshot()

    def execute(
        self,
        definition: WorkflowDefinitionInput,
        *,
        execution_id: UUID | None = None,
    ) -> WorkflowExecution:
        """Create and synchronously run a workflow, preserving the Day 7 API."""
        pending = self.create_execution(definition, execution_id=execution_id)
        return self.run(pending.execution_id)

    def run(self, execution_id: UUID) -> WorkflowExecution:
        """Run an existing pending execution to a terminal state."""
        with self._lock:
            execution = self._active_execution(execution_id)
            if execution.status != WorkflowStatus.PENDING:
                raise InvalidExecutionStateError(
                    f"Execution {execution_id} cannot run from {execution.status.value!r}."
                )
            started_at = self._now()
            execution.transition_to(WorkflowStatus.RUNNING)
            execution.started_at = started_at
            execution.events.append(
                WorkflowEvent(
                    event_type=WorkflowEventType.WORKFLOW_STARTED,
                    execution_id=execution.execution_id,
                    timestamp=started_at,
                    from_status=WorkflowStatus.PENDING.value,
                    to_status=WorkflowStatus.RUNNING.value,
                    metadata={
                        "workflow_name": execution.workflow.name,
                        "task_count": len(execution.workflow.tasks),
                    },
                )
            )
            ordered_tasks = self._validator.topological_order(execution.workflow)

        executed_steps = 0
        limit_event_emitted = False
        for task in ordered_tasks:
            with self._lock:
                if execution.cancellation_requested:
                    self._cancel_running_execution(execution)
                    return execution.model_copy(deep=True)

                blocked_by = [
                    dependency_id
                    for dependency_id in task.dependency_ids
                    if execution.task_results[dependency_id].status != TaskStatus.COMPLETED
                ]
                if blocked_by:
                    self._block_task(execution, task, blocked_by)
                    continue

                if executed_steps >= self._max_execution_steps:
                    if not limit_event_emitted:
                        execution.events.append(
                            WorkflowEvent(
                                event_type=WorkflowEventType.EXECUTION_LIMIT_REACHED,
                                execution_id=execution.execution_id,
                                timestamp=self._now(),
                                reason="The maximum number of execution steps was reached.",
                                metadata={"maximum_steps": self._max_execution_steps},
                            )
                        )
                        limit_event_emitted = True
                    self._skip_task(
                        execution,
                        task,
                        code="execution_step_limit",
                        message="Task was not run because the execution step limit was reached.",
                    )
                    continue

                self._start_task(execution, task)
                executed_steps += 1

            self._run_task(execution, task)

        with self._lock:
            if execution.cancellation_requested:
                self._cancel_running_execution(execution)
            else:
                failed = any(
                    result.status in {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.SKIPPED}
                    for result in execution.task_results.values()
                )
                completed_at = self._now()
                new_status = WorkflowStatus.FAILED if failed else WorkflowStatus.COMPLETED
                execution.transition_to(new_status)
                execution.completed_at = completed_at
                execution.events.append(
                    WorkflowEvent(
                        event_type=(
                            WorkflowEventType.WORKFLOW_FAILED
                            if failed
                            else WorkflowEventType.WORKFLOW_COMPLETED
                        ),
                        execution_id=execution.execution_id,
                        timestamp=completed_at,
                        from_status=WorkflowStatus.RUNNING.value,
                        to_status=new_status.value,
                        reason=(
                            "One or more tasks failed, were blocked, or were skipped."
                            if failed
                            else None
                        ),
                    )
                )
                self._archive(execution)
            return execution.model_copy(deep=True)

    def cancel(self, execution_id: UUID) -> WorkflowExecutionSnapshot:
        """Cancel pending work or request cooperative cancellation between tasks."""
        with self._lock:
            execution = self._active_execution(execution_id)
            if execution.status == WorkflowStatus.PENDING:
                self._skip_pending_tasks(
                    execution,
                    code="workflow_cancelled",
                    message="Task was not run because the workflow was cancelled.",
                )
                completed_at = self._now()
                execution.transition_to(WorkflowStatus.CANCELLED)
                execution.completed_at = completed_at
                execution.events.append(
                    WorkflowEvent(
                        event_type=WorkflowEventType.WORKFLOW_CANCELLED,
                        execution_id=execution.execution_id,
                        timestamp=completed_at,
                        from_status=WorkflowStatus.PENDING.value,
                        to_status=WorkflowStatus.CANCELLED.value,
                        reason="Workflow cancelled before execution started.",
                    )
                )
                self._archive(execution)
                return execution.snapshot()

            if execution.status == WorkflowStatus.RUNNING:
                if not execution.cancellation_requested:
                    execution.cancellation_requested = True
                    execution.events.append(
                        WorkflowEvent(
                            event_type=WorkflowEventType.WORKFLOW_CANCELLATION_REQUESTED,
                            execution_id=execution.execution_id,
                            timestamp=self._now(),
                            from_status=WorkflowStatus.RUNNING.value,
                            to_status=WorkflowStatus.RUNNING.value,
                            reason=(
                                "Cancellation will take effect after the current "
                                "synchronous agent call returns."
                            ),
                        )
                    )
                return execution.snapshot()

            raise InvalidExecutionStateError(
                f"Execution {execution_id} cannot be cancelled from {execution.status.value!r}."
            )

    def get_execution(self, execution_id: UUID) -> WorkflowExecutionSnapshot:
        """Return a detached snapshot of an active or terminal execution."""
        with self._lock:
            execution = self._active.get(execution_id)
            if execution is not None:
                return execution.snapshot()
            snapshot = self._history.get(execution_id)
            if snapshot is None:
                raise ExecutionNotFoundError(f"Execution {execution_id} was not found.")
            return snapshot.model_copy(deep=True)

    def list_executions(self, *, limit: int | None = None) -> list[WorkflowExecutionSnapshot]:
        """List retained terminal snapshots, newest first."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1.")
        with self._lock:
            snapshots = reversed(self._history.values())
            if limit is not None:
                snapshots = list(snapshots)[:limit]
            return [snapshot.model_copy(deep=True) for snapshot in snapshots]

    def _active_execution(self, execution_id: UUID) -> WorkflowExecution:
        execution = self._active.get(execution_id)
        if execution is not None:
            return execution
        snapshot = self._history.get(execution_id)
        if snapshot is not None:
            raise InvalidExecutionStateError(
                f"Execution {execution_id} is already terminal ({snapshot.status.value})."
            )
        raise ExecutionNotFoundError(f"Execution {execution_id} was not found.")

    def _run_task(self, execution: WorkflowExecution, task: WorkflowTask) -> None:
        try:
            agent_input = self._agent_input(execution, task)
        except Exception as exc:
            logger.error(
                "Workflow task input preparation failed",
                extra={
                    "execution_id": str(execution.execution_id),
                    "task_id": task.task_id,
                    "agent_type": task.agent_type.value,
                    "exception_type": type(exc).__name__,
                },
            )
            self._fail_task(
                execution,
                task,
                code="task_input_error",
                message="The task input could not be prepared safely.",
                details={"exception_type": type(exc).__name__},
            )
            return

        if self._input_size(agent_input) > self._validator.max_task_input_bytes:
            self._fail_task(
                execution,
                task,
                code="task_input_limit",
                message="The agent input exceeded the configured size limit.",
                details={"maximum_input_bytes": self._validator.max_task_input_bytes},
            )
            return

        try:
            agent_result = self._agents[task.agent_type].execute(agent_input)
        except Exception as exc:
            logger.error(
                "Workflow agent raised an unexpected exception",
                extra={
                    "execution_id": str(execution.execution_id),
                    "task_id": task.task_id,
                    "agent_type": task.agent_type.value,
                    "exception_type": type(exc).__name__,
                },
            )
            self._fail_task(
                execution,
                task,
                code="agent_exception",
                message="The registered agent raised an unexpected exception.",
                details={"exception_type": type(exc).__name__},
            )
            return

        if not isinstance(agent_result, AgentExecutionResult):
            logger.error(
                "Workflow agent returned an invalid result contract",
                extra={
                    "execution_id": str(execution.execution_id),
                    "task_id": task.task_id,
                    "agent_type": task.agent_type.value,
                    "result_type": type(agent_result).__name__,
                },
            )
            self._fail_task(
                execution,
                task,
                code="invalid_agent_result",
                message="The agent returned an invalid execution result.",
            )
            return

        if agent_result.status == AgentExecutionStatus.FAILED:
            agent_error = agent_result.error
            if agent_error is None:
                self._fail_task(
                    execution,
                    task,
                    code="invalid_agent_failure",
                    message="The agent returned an invalid failure result.",
                )
                return
            logger.warning(
                "Workflow agent reported a task failure",
                extra={
                    "execution_id": str(execution.execution_id),
                    "task_id": task.task_id,
                    "agent_type": task.agent_type.value,
                    "error_category": agent_error.code.value,
                },
            )
            self._fail_task(
                execution,
                task,
                code=agent_error.code.value,
                message=_SAFE_AGENT_ERROR_MESSAGES.get(
                    agent_error.code,
                    "The agent could not complete the task.",
                ),
                details={"agent_error_code": agent_error.code.value},
            )
            return

        if self._result_size(agent_result) > self._max_result_bytes:
            self._fail_task(
                execution,
                task,
                code="result_too_large",
                message="The agent result exceeded the configured size limit.",
                details={"maximum_result_bytes": self._max_result_bytes},
            )
            return

        safe_tool_result = None
        if task.tool_request is not None:
            agent = self._agents[task.agent_type]
            request = ToolExecutionRequest(
                tool_id=task.tool_request.tool_id,
                agent_id=agent.identity.agent_id,
                arguments=task.tool_request.arguments,
                agent_capabilities=agent.supported_capabilities,
                execution_id=str(execution.execution_id),
                workflow_execution_id=str(execution.execution_id),
                task_id=task.task_id,
            )
            with self._lock:
                execution.events.append(
                    WorkflowEvent(
                        event_type=WorkflowEventType.TASK_TOOL_EXECUTION_STARTED,
                        execution_id=execution.execution_id,
                        task_id=task.task_id,
                        timestamp=self._now(),
                        metadata={"tool_id": task.tool_request.tool_id},
                    )
                )
            tool_result = self._tool_executor.execute(
                request,
                agent_capabilities=agent.supported_capabilities,
            )
            safe_tool_result = self._safe_tool_result(tool_result)
            succeeded = tool_result.status == ToolExecutionStatus.SUCCEEDED
            with self._lock:
                execution.events.append(
                    WorkflowEvent(
                        event_type=(
                            WorkflowEventType.TASK_TOOL_EXECUTION_COMPLETED
                            if succeeded
                            else WorkflowEventType.TASK_TOOL_EXECUTION_FAILED
                        ),
                        execution_id=execution.execution_id,
                        task_id=task.task_id,
                        timestamp=self._now(),
                        reason=(
                            None if succeeded else "The requested tool could not complete safely."
                        ),
                        metadata={
                            "tool_id": task.tool_request.tool_id,
                            "status": tool_result.status.value,
                        },
                    )
                )
            if not succeeded:
                error_code = (
                    tool_result.error.code
                    if tool_result.error is not None
                    else "tool_execution_failed"
                )
                self._fail_task(
                    execution,
                    task,
                    code=f"tool_{error_code}",
                    message="The requested tool could not complete safely.",
                    details={"tool_error_code": error_code},
                    agent_result=agent_result,
                    tool_result=safe_tool_result,
                )
                return

        if task.agent_type == AgentRole.REVIEWER:
            verdict = agent_result.output.result_data.get("verdict")
            if verdict != "passed":
                code = "review_not_evaluated" if verdict == "not_evaluated" else "review_rejected"
                self._fail_task(
                    execution,
                    task,
                    code=code,
                    message=(
                        "The reviewer did not evaluate the result."
                        if verdict == "not_evaluated"
                        else "The reviewer did not approve the result."
                    ),
                    details={"review_verdict": str(verdict or "invalid")},
                    agent_result=agent_result,
                    tool_result=safe_tool_result,
                )
                return

        with self._lock:
            result = execution.task_results[task.task_id]
            completed_at = self._now()
            result.agent_result = agent_result
            result.tool_result = safe_tool_result
            result.completed_at = completed_at
            result.transition_to(TaskStatus.COMPLETED)
            execution.events.append(
                WorkflowEvent(
                    event_type=WorkflowEventType.TASK_COMPLETED,
                    execution_id=execution.execution_id,
                    task_id=task.task_id,
                    timestamp=completed_at,
                    from_status=TaskStatus.RUNNING.value,
                    to_status=TaskStatus.COMPLETED.value,
                    metadata={
                        "agent_type": task.agent_type.value,
                        "execution_duration_ms": agent_result.execution_duration_ms,
                    },
                )
            )

    def _start_task(self, execution: WorkflowExecution, task: WorkflowTask) -> None:
        result = execution.task_results[task.task_id]
        started_at = self._now()
        result.transition_to(TaskStatus.RUNNING)
        result.started_at = started_at
        execution.execution_order.append(task.task_id)
        execution.events.append(
            WorkflowEvent(
                event_type=WorkflowEventType.TASK_STARTED,
                execution_id=execution.execution_id,
                task_id=task.task_id,
                timestamp=started_at,
                from_status=TaskStatus.PENDING.value,
                to_status=TaskStatus.RUNNING.value,
                metadata={"agent_type": task.agent_type.value},
            )
        )

    def _fail_task(
        self,
        execution: WorkflowExecution,
        task: WorkflowTask,
        *,
        code: str,
        message: str,
        details: dict[str, str | int] | None = None,
        agent_result: AgentExecutionResult | None = None,
        tool_result: ToolExecutionResult | None = None,
    ) -> None:
        with self._lock:
            result = execution.task_results[task.task_id]
            failed_at = self._now()
            result.error = WorkflowTaskError(
                code=code,
                message=message,
                details=details or {},
                occurred_at=failed_at,
            )
            result.agent_result = agent_result
            result.tool_result = tool_result
            result.completed_at = failed_at
            result.transition_to(TaskStatus.FAILED)
            execution.events.append(
                WorkflowEvent(
                    event_type=WorkflowEventType.TASK_FAILED,
                    execution_id=execution.execution_id,
                    task_id=task.task_id,
                    timestamp=failed_at,
                    from_status=TaskStatus.RUNNING.value,
                    to_status=TaskStatus.FAILED.value,
                    reason=message,
                    metadata={
                        "agent_type": task.agent_type.value,
                        "error": {
                            "code": code,
                            "message": message,
                            "details": details or {},
                        },
                    },
                )
            )

    def _block_task(
        self,
        execution: WorkflowExecution,
        task: WorkflowTask,
        blocked_by: list[str],
    ) -> None:
        result = execution.task_results[task.task_id]
        blocked_at = self._now()
        result.transition_to(TaskStatus.BLOCKED)
        result.completed_at = blocked_at
        result.error = WorkflowTaskError(
            code="dependency_failed",
            message="Task was not run because one or more dependencies did not complete.",
            details={"blocked_by": blocked_by},
            occurred_at=blocked_at,
        )
        execution.events.append(
            WorkflowEvent(
                event_type=WorkflowEventType.TASK_BLOCKED,
                execution_id=execution.execution_id,
                task_id=task.task_id,
                timestamp=blocked_at,
                from_status=TaskStatus.PENDING.value,
                to_status=TaskStatus.BLOCKED.value,
                reason=result.error.message,
                metadata={"blocked_by": blocked_by},
            )
        )

    def _skip_task(
        self,
        execution: WorkflowExecution,
        task: WorkflowTask,
        *,
        code: str,
        message: str,
    ) -> None:
        result = execution.task_results[task.task_id]
        skipped_at = self._now()
        result.transition_to(TaskStatus.SKIPPED)
        result.completed_at = skipped_at
        result.error = WorkflowTaskError(
            code=code,
            message=message,
            occurred_at=skipped_at,
        )
        execution.events.append(
            WorkflowEvent(
                event_type=WorkflowEventType.TASK_SKIPPED,
                execution_id=execution.execution_id,
                task_id=task.task_id,
                timestamp=skipped_at,
                from_status=TaskStatus.PENDING.value,
                to_status=TaskStatus.SKIPPED.value,
                reason=message,
            )
        )

    def _skip_pending_tasks(
        self,
        execution: WorkflowExecution,
        *,
        code: str,
        message: str,
    ) -> None:
        for task in execution.workflow.tasks:
            if execution.task_results[task.task_id].status == TaskStatus.PENDING:
                self._skip_task(execution, task, code=code, message=message)

    def _cancel_running_execution(self, execution: WorkflowExecution) -> None:
        self._skip_pending_tasks(
            execution,
            code="workflow_cancelled",
            message="Task was not run because the workflow was cancelled.",
        )
        completed_at = self._now()
        execution.transition_to(WorkflowStatus.CANCELLED)
        execution.completed_at = completed_at
        execution.events.append(
            WorkflowEvent(
                event_type=WorkflowEventType.WORKFLOW_CANCELLED,
                execution_id=execution.execution_id,
                timestamp=completed_at,
                from_status=WorkflowStatus.RUNNING.value,
                to_status=WorkflowStatus.CANCELLED.value,
                reason="Workflow cancelled between task executions.",
            )
        )
        self._archive(execution)

    def _archive(self, execution: WorkflowExecution) -> None:
        self._history[execution.execution_id] = execution.snapshot()
        self._history.move_to_end(execution.execution_id)
        while len(self._history) > self._max_history_size:
            self._history.popitem(last=False)
        self._active.pop(execution.execution_id, None)

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
                    tool_output=(
                        dependency_result.tool_result.output.output
                        if dependency_result.tool_result is not None
                        and dependency_result.tool_result.output is not None
                        else None
                    ),
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

    def _result_size(self, agent_result: AgentExecutionResult) -> int:
        encoded = json.dumps(
            agent_result.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return len(encoded)

    @staticmethod
    def _safe_tool_result(result: ToolExecutionResult) -> ToolExecutionResult:
        safe_result = result.model_copy(deep=True)
        if safe_result.error is not None:
            safe_result.error.details = {}
        return safe_result

    @staticmethod
    def _input_size(agent_input: AgentInput) -> int:
        encoded = json.dumps(
            agent_input.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return len(encoded)

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


__all__ = [
    "ExecutionNotFoundError",
    "InvalidExecutionStateError",
    "WorkflowEngine",
]
