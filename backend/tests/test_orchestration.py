import pytest
from agentforge.agents import PlannerAgent
from agentforge.domain.agents import AgentExecutionStatus, AgentOutput, AgentRole
from agentforge.domain.workflows import (
    TaskStatus,
    WorkflowEventType,
    WorkflowStatus,
    WorkflowValidationError,
)
from agentforge.tools import (
    ToolDefinition,
    ToolExecutionStatus,
    ToolExecutor,
    ToolRegistry,
)
from agentforge.workflow import WorkflowEngine, WorkflowOrchestrator


def test_planner_prepares_validated_pending_work_and_requires_explicit_start() -> None:
    orchestrator = WorkflowOrchestrator()

    prepared = orchestrator.prepare(
        "inspect the supplied labels",
        input_data={"labels": ["alpha", "beta"]},
        review_criteria=["observations"],
    )

    assert prepared.planner_result.metadata["execution_mode"] == "deterministic_mock"
    assert prepared.planner_result.output.metadata["executable"] is False
    assert prepared.execution.status == WorkflowStatus.PENDING
    assert prepared.execution.execution_order == []
    assert [task.agent_type for task in prepared.workflow.tasks] == [
        AgentRole.ANALYST,
        AgentRole.REVIEWER,
    ]
    assert prepared.workflow.tasks[-1].dependency_ids == ["draft-1"]

    completed = orchestrator.start(prepared.execution.execution_id)

    assert completed.status == WorkflowStatus.COMPLETED
    assert completed.execution_order == ["draft-1", "final_review"]
    assert completed.task_results["final_review"].agent_result.output.result_data["verdict"] == (
        "passed"
    )


def test_invalid_planner_workflow_is_rejected_before_execution_registration() -> None:
    class DuplicateStepPlanner(PlannerAgent):
        def _execute(self, agent_input):
            return AgentOutput(
                agent_id=self.identity.agent_id,
                status=AgentExecutionStatus.SUCCEEDED,
                summary="Proposed duplicate steps.",
                result_data={
                    "objective": agent_input.task_description,
                    "plan_status": "draft_only",
                    "proposed_steps": [
                        {
                            "step_id": "same",
                            "assigned_role": "analyst",
                            "instruction": "First step",
                        },
                        {
                            "step_id": "same",
                            "assigned_role": "researcher",
                            "instruction": "Second step",
                        },
                    ],
                },
            )

    orchestrator = WorkflowOrchestrator(planner=DuplicateStepPlanner())
    with pytest.raises(WorkflowValidationError, match="not unique"):
        orchestrator.prepare("make a plan")


def test_tool_request_executes_through_executor_and_propagates_dependency_output() -> None:
    engine = WorkflowEngine()
    execution = engine.create_execution(
        {
            "name": "tool workflow",
            "tasks": [
                {
                    "task_id": "calculate",
                    "agent_type": "analyst",
                    "tool_request": {
                        "tool_id": "calculator",
                        "arguments": {"operation": "add", "left": 2, "right": 3},
                    },
                },
                {
                    "task_id": "inspect",
                    "agent_type": "researcher",
                    "dependency_ids": ["calculate"],
                },
            ],
        }
    )

    result = engine.run(execution.execution_id)

    calculate = result.task_results["calculate"]
    assert result.status == WorkflowStatus.COMPLETED
    assert calculate.tool_result.status == ToolExecutionStatus.SUCCEEDED
    assert calculate.tool_result.output.output["result"] == 5
    assert (
        result.task_results["inspect"].agent_result.output.result_data["supplied_information"] == {}
    )
    previous = result.task_results["inspect"].agent_result.output.result_data["previous_results"][0]
    assert previous["tool_output"]["result"] == 5
    assert WorkflowEventType.TASK_TOOL_EXECUTION_COMPLETED in [
        event.event_type for event in result.events
    ]


def test_declared_tool_handler_waits_until_explicit_execution_start() -> None:
    calls = []
    tool = ToolDefinition(
        tool_id="recording_tool",
        name="recording_tool",
        description="Record whether the handler was invoked.",
        required_capabilities={"analyze_supplied_data"},
        handler=lambda arguments: calls.append(arguments) or {"invoked": True},
    )
    engine = WorkflowEngine(tool_executor=ToolExecutor(ToolRegistry([tool])))
    pending = engine.create_execution(
        {
            "tasks": [
                {
                    "task_id": "call-tool",
                    "agent_type": "analyst",
                    "tool_request": {"tool_id": "recording_tool", "arguments": {}},
                }
            ]
        }
    )

    assert calls == []
    assert pending.status == WorkflowStatus.PENDING

    engine.run(pending.execution_id)

    assert calls == [{}]


def test_tool_permission_is_checked_before_workflow_execution() -> None:
    engine = WorkflowEngine()
    with pytest.raises(WorkflowValidationError, match="invalid or unauthorized"):
        engine.create_execution(
            {
                "tasks": [
                    {
                        "task_id": "unauthorized",
                        "agent_type": "researcher",
                        "tool_request": {
                            "tool_id": "calculator",
                            "arguments": {"operation": "add", "left": 1, "right": 1},
                        },
                    }
                ]
            }
        )


def test_tool_failure_fails_task_and_blocks_dependents_without_leaking_details() -> None:
    engine = WorkflowEngine()
    pending = engine.create_execution(
        {
            "tasks": [
                {
                    "task_id": "bad-tool",
                    "agent_type": "analyst",
                    "tool_request": {
                        "tool_id": "calculator",
                        "arguments": {"operation": "divide", "left": 1, "right": 0},
                    },
                },
                {
                    "task_id": "dependent",
                    "agent_type": "analyst",
                    "dependency_ids": ["bad-tool"],
                },
            ]
        }
    )

    result = engine.run(pending.execution_id)
    failed = result.task_results["bad-tool"]

    assert result.status == WorkflowStatus.FAILED
    assert failed.status == TaskStatus.FAILED
    assert failed.tool_result.status == ToolExecutionStatus.FAILED
    assert failed.tool_result.error.details == {}
    assert result.task_results["dependent"].status == TaskStatus.BLOCKED
    assert result.events[-1].event_type == WorkflowEventType.WORKFLOW_FAILED


def test_reviewer_rejection_is_a_workflow_failure_with_visible_verdict() -> None:
    execution = WorkflowEngine().execute(
        {
            "tasks": [
                {
                    "task_id": "review",
                    "agent_type": "reviewer",
                    "input_data": {"supplied": "nothing matched"},
                    "review_criteria": ["required phrase"],
                }
            ]
        }
    )

    review = execution.task_results["review"]
    assert execution.status == WorkflowStatus.FAILED
    assert review.status == TaskStatus.FAILED
    assert review.error.code == "review_rejected"
    assert review.agent_result.output.result_data["verdict"] == "failed"


def test_reviewer_without_criteria_is_not_silently_accepted() -> None:
    execution = WorkflowEngine().execute(
        {"tasks": [{"task_id": "review", "agent_type": "reviewer"}]}
    )

    assert execution.status == WorkflowStatus.FAILED
    assert execution.task_results["review"].error.code == "review_not_evaluated"
