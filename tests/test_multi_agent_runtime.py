import time

import pytest

from pmaa.multi_agent.blackboard import InMemoryBlackboard
from pmaa.multi_agent.contracts import (
    AgentMessage,
    AgentMessageType,
    AgentResult,
    AgentSpec,
    AgentStatus,
    AgentTask,
)
from pmaa.multi_agent.registry import AgentRegistry
from pmaa.multi_agent.runtime import AgentExecutionContext, CentralAgentRuntime


def make_registry(handler) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(
        AgentSpec(
            agent_id="research",
            name="Research",
            description="Research agent",
            allowed_tools=["web_search"],
            max_retries=2,
        ),
        handler,
    )
    return registry


def successful_handler(
    task: AgentTask, context: AgentExecutionContext
) -> AgentResult:
    context.report_progress("searching", query=task.objective)
    context.request_delegation(
        target_capability="memory.retrieve",
        objective="Get preferences",
        reason="Personalize result",
    )
    return AgentResult(
        task_id=task.task_id,
        agent_id=task.assigned_to,
        status=AgentStatus.COMPLETED,
        summary="Done",
        confidence=0.9,
    )


def test_runtime_dispatches_and_records_central_messages() -> None:
    runtime = CentralAgentRuntime(make_registry(successful_handler))
    task = AgentTask(
        task_id="research-1",
        assigned_to="research",
        objective="Research LangGraph",
        allowed_tools=["web_search"],
        max_retries=2,
    )

    result = runtime.dispatch(task)
    messages = runtime.blackboard.list_messages(task.task_id)

    assert result.status == AgentStatus.COMPLETED
    assert runtime.blackboard.get_result(task.task_id) == result
    assert all(message.receiver == "supervisor" for message in messages)
    assert AgentMessageType.DELEGATION_REQUEST in {
        message.message_type for message in messages
    }


def test_runtime_converts_handler_exception_to_failed_result() -> None:
    def failing_handler(task: AgentTask, context: AgentExecutionContext) -> AgentResult:
        raise RuntimeError("search unavailable")

    runtime = CentralAgentRuntime(make_registry(failing_handler))
    result = runtime.dispatch(
        AgentTask(assigned_to="research", objective="Research", max_retries=2)
    )

    assert result.status == AgentStatus.FAILED
    assert result.errors == ["search unavailable"]


def test_runtime_rejects_result_from_another_agent() -> None:
    def bad_handler(task: AgentTask, context: AgentExecutionContext) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id="email",
            status=AgentStatus.COMPLETED,
        )

    runtime = CentralAgentRuntime(make_registry(bad_handler))
    result = runtime.dispatch(
        AgentTask(assigned_to="research", objective="Research", max_retries=2)
    )

    assert result.status == AgentStatus.FAILED
    assert "identity" in result.errors[0]


def test_runtime_executes_independent_tasks_in_parallel() -> None:
    def delayed_handler(task: AgentTask, context: AgentExecutionContext) -> AgentResult:
        time.sleep(0.05)
        return AgentResult(
            task_id=task.task_id,
            agent_id=task.assigned_to,
            status=AgentStatus.COMPLETED,
            summary=task.objective,
        )

    runtime = CentralAgentRuntime(make_registry(delayed_handler), max_concurrency=2)
    tasks = [
        AgentTask(
            task_id=f"task-{index}",
            assigned_to="research",
            objective=f"topic-{index}",
            max_retries=2,
        )
        for index in range(2)
    ]

    results = runtime.dispatch_parallel(tasks)

    assert [result.task_id for result in results] == ["task-0", "task-1"]
    assert all(result.status == AgentStatus.COMPLETED for result in results)


def test_parallel_dispatch_rejects_dependent_tasks() -> None:
    runtime = CentralAgentRuntime(make_registry(successful_handler))
    task = AgentTask(
        assigned_to="research",
        objective="Dependent research",
        depends_on=["parent"],
        max_retries=2,
    )

    with pytest.raises(ValueError, match="independent or have completed dependencies"):
        runtime.dispatch_parallel([task])


def test_blackboard_blocks_child_to_child_messages() -> None:
    blackboard = InMemoryBlackboard()
    task = AgentTask(task_id="task-1", assigned_to="research", objective="Research")
    blackboard.add_task(task)

    with pytest.raises(ValueError, match="only send messages to supervisor"):
        blackboard.add_message(
            AgentMessage(
                task_id=task.task_id,
                sender="research",
                receiver="memory",
                message_type=AgentMessageType.DELEGATION_REQUEST,
            )
        )
