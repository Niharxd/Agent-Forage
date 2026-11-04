"""Workflow structure checks and deterministic dependency ordering."""

import heapq
import json
from collections import defaultdict
from collections.abc import Mapping
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, ValidationError

from agentforge.domain.workflows.models import (
    MAX_TASK_INPUT_BYTES,
    WorkflowDefinition,
    WorkflowTask,
)

DEFAULT_MAX_WORKFLOW_TASKS = 25
WorkflowDefinitionInput: TypeAlias = WorkflowDefinition | Mapping[str, object]


class WorkflowValidationIssue(BaseModel):
    """A machine-readable workflow validation problem."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    task_id: str | None = None
    location: tuple[str | int, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation of this issue."""
        issue: dict[str, object] = self.model_dump(exclude_none=True)
        issue["location"] = list(self.location)
        return issue


class WorkflowValidationError(ValueError):
    """Raised when a workflow definition is not safe to execute."""

    def __init__(self, issues: list[WorkflowValidationIssue]) -> None:
        self.issues = tuple(issues)
        summary = "; ".join(issue.message for issue in issues)
        super().__init__(summary)


class WorkflowValidator:
    """Validate workflow bounds and DAG structure before execution."""

    def __init__(
        self,
        max_tasks: int = DEFAULT_MAX_WORKFLOW_TASKS,
        max_task_input_bytes: int = MAX_TASK_INPUT_BYTES,
    ) -> None:
        if not 1 <= max_tasks <= DEFAULT_MAX_WORKFLOW_TASKS:
            raise ValueError(f"max_tasks must be between 1 and {DEFAULT_MAX_WORKFLOW_TASKS}")
        if not 1 <= max_task_input_bytes <= MAX_TASK_INPUT_BYTES:
            raise ValueError(f"max_task_input_bytes must be between 1 and {MAX_TASK_INPUT_BYTES}")
        self.max_tasks = max_tasks
        self.max_task_input_bytes = max_task_input_bytes

    def validate(self, definition: WorkflowDefinitionInput) -> WorkflowDefinition:
        """Parse and validate a workflow, raising structured errors on invalid input."""
        self._precheck_task_limit(definition)
        workflow = self._parse(definition)
        issues: list[WorkflowValidationIssue] = []
        if len(workflow.tasks) > self.max_tasks:
            issues.append(
                WorkflowValidationIssue(
                    code="maximum_task_limit",
                    message=(
                        f"Workflow has {len(workflow.tasks)} tasks; "
                        f"the maximum is {self.max_tasks}."
                    ),
                    location=("tasks",),
                )
            )

        for index, task in enumerate(workflow.tasks):
            input_size = len(
                json.dumps(
                    task.input_data,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if input_size > self.max_task_input_bytes:
                issues.append(
                    WorkflowValidationIssue(
                        code="task_input_limit",
                        message=(
                            f"Task {task.task_id!r} input is {input_size} bytes; "
                            f"the maximum is {self.max_task_input_bytes}."
                        ),
                        task_id=task.task_id,
                        location=("tasks", index, "input_data"),
                    )
                )

        task_ids = {task.task_id for task in workflow.tasks}
        seen_task_ids: set[str] = set()
        for index, task in enumerate(workflow.tasks):
            if task.task_id in seen_task_ids:
                issues.append(
                    WorkflowValidationIssue(
                        code="duplicate_task_id",
                        message=f"Task ID {task.task_id!r} is not unique.",
                        task_id=task.task_id,
                        location=("tasks", index, "task_id"),
                    )
                )
            seen_task_ids.add(task.task_id)

        for index, task in enumerate(workflow.tasks):
            if len(task.dependency_ids) != len(set(task.dependency_ids)):
                issues.append(
                    WorkflowValidationIssue(
                        code="duplicate_dependency",
                        message=f"Task {task.task_id!r} lists a dependency more than once.",
                        task_id=task.task_id,
                        location=("tasks", index, "dependency_ids"),
                    )
                )
            for dependency_id in task.dependency_ids:
                if dependency_id == task.task_id:
                    issues.append(
                        WorkflowValidationIssue(
                            code="self_dependency",
                            message=f"Task {task.task_id!r} cannot depend on itself.",
                            task_id=task.task_id,
                            location=("tasks", index, "dependency_ids"),
                        )
                    )
                elif dependency_id not in task_ids:
                    issues.append(
                        WorkflowValidationIssue(
                            code="missing_dependency",
                            message=(
                                f"Task {task.task_id!r} depends on unknown task {dependency_id!r}."
                            ),
                            task_id=task.task_id,
                            location=("tasks", index, "dependency_ids"),
                        )
                    )

        if issues:
            raise WorkflowValidationError(issues)

        if self._has_cycle(workflow.tasks):
            raise WorkflowValidationError(
                [
                    WorkflowValidationIssue(
                        code="circular_dependency",
                        message="Workflow dependencies must form a directed acyclic graph.",
                        location=("tasks",),
                    )
                ]
            )
        return workflow

    def _precheck_task_limit(self, definition: WorkflowDefinitionInput) -> None:
        if not isinstance(definition, Mapping):
            return
        tasks = definition.get("tasks")
        if not isinstance(tasks, (list, tuple)) or len(tasks) <= self.max_tasks:
            return
        raise WorkflowValidationError(
            [
                WorkflowValidationIssue(
                    code="maximum_task_limit",
                    message=f"Workflow has more than {self.max_tasks} tasks.",
                    location=("tasks",),
                )
            ]
        )

    def topological_order(self, definition: WorkflowDefinitionInput) -> tuple[WorkflowTask, ...]:
        """Return a stable topological order, lexically breaking ready-task ties."""
        return self._order_validated(self.validate(definition))

    def validate_and_order(
        self, definition: WorkflowDefinitionInput
    ) -> tuple[WorkflowDefinition, tuple[WorkflowTask, ...]]:
        """Validate once and return both the normalized definition and stable order."""
        workflow = self.validate(definition)
        return workflow, self._order_validated(workflow)

    def _parse(self, definition: WorkflowDefinitionInput) -> WorkflowDefinition:
        try:
            return WorkflowDefinition.model_validate(definition)
        except ValidationError as exc:
            issues = [
                WorkflowValidationIssue(
                    code=issue["type"],
                    message=issue["msg"],
                    location=tuple(issue["loc"]),
                )
                for issue in exc.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            ]
            raise WorkflowValidationError(issues) from exc

    def _has_cycle(self, tasks: list[WorkflowTask]) -> bool:
        in_degree = {task.task_id: len(task.dependency_ids) for task in tasks}
        dependents: dict[str, list[str]] = defaultdict(list)
        for task in tasks:
            for dependency_id in task.dependency_ids:
                dependents[dependency_id].append(task.task_id)

        ready = [task_id for task_id, count in in_degree.items() if count == 0]
        visited = 0
        while ready:
            task_id = heapq.heappop(ready)
            visited += 1
            for dependent_id in dependents[task_id]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    heapq.heappush(ready, dependent_id)
        return visited != len(tasks)

    @staticmethod
    def _order_validated(workflow: WorkflowDefinition) -> tuple[WorkflowTask, ...]:
        dependents: dict[str, list[str]] = defaultdict(list)
        remaining_dependencies: dict[str, int] = {}
        tasks_by_id = {task.task_id: task for task in workflow.tasks}
        for task in workflow.tasks:
            remaining_dependencies[task.task_id] = len(task.dependency_ids)
            for dependency_id in task.dependency_ids:
                dependents[dependency_id].append(task.task_id)

        ready = [task_id for task_id, count in remaining_dependencies.items() if count == 0]
        heapq.heapify(ready)
        ordered: list[WorkflowTask] = []
        while ready:
            task_id = heapq.heappop(ready)
            ordered.append(tasks_by_id[task_id])
            for dependent_id in sorted(dependents[task_id]):
                remaining_dependencies[dependent_id] -= 1
                if remaining_dependencies[dependent_id] == 0:
                    heapq.heappush(ready, dependent_id)
        return tuple(ordered)
