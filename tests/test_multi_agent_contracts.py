import pytest
from pydantic import ValidationError

from pmaa.multi_agent.contracts import AgentTask, ToolRequest, ToolResult


def test_agent_task_normalizes_tools_and_dependencies() -> None:
    task = AgentTask(
        task_id="child-2",
        assigned_to="web_research",
        objective="Research a topic",
        allowed_tools=["web_search", "web_search"],
        depends_on=["child-1", "child-1"],
    )

    assert task.allowed_tools == ["web_search"]
    assert task.depends_on == ["child-1"]


def test_agent_task_rejects_self_dependency() -> None:
    with pytest.raises(ValidationError, match="depend on itself"):
        AgentTask(
            task_id="same",
            assigned_to="memory",
            objective="Store preference",
            depends_on=["same"],
        )


def test_agent_task_rejects_invalid_retry_state() -> None:
    with pytest.raises(ValidationError, match="retry_count"):
        AgentTask(
            assigned_to="email",
            objective="Draft reply",
            retry_count=2,
            max_retries=1,
        )


def test_tool_contract_keeps_request_identity() -> None:
    request = ToolRequest(
        task_id="task-1",
        agent_id="web_research",
        tool_name="web_search",
        arguments={"query": "LangGraph"},
    )
    result = ToolResult(
        request_id=request.request_id,
        task_id=request.task_id,
        agent_id=request.agent_id,
        tool_name=request.tool_name,
        success=True,
        output={"count": 3},
    )

    assert result.request_id == request.request_id
    assert result.output == {"count": 3}
