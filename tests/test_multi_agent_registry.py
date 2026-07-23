import pytest

from pmaa.multi_agent.contracts import AgentResult, AgentSpec, AgentStatus, AgentTask
from pmaa.multi_agent.registry import AgentRegistry


def handler(task: AgentTask, context: object) -> AgentResult:
    return AgentResult(
        task_id=task.task_id,
        agent_id=task.assigned_to,
        status=AgentStatus.COMPLETED,
    )


def build_spec(*, enabled: bool = True) -> AgentSpec:
    return AgentSpec(
        agent_id="web_research",
        name="Web Research Agent",
        description="Researches current web information.",
        allowed_tools=["web_search"],
        enabled=enabled,
    )


def test_registry_registers_and_lists_agents() -> None:
    registry = AgentRegistry()
    registry.register(build_spec(), handler)

    assert registry.get_handler("web_research") is handler
    assert [item.agent_id for item in registry.list_specs()] == ["web_research"]


def test_registry_rejects_duplicate_agent() -> None:
    registry = AgentRegistry()
    registry.register(build_spec(), handler)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(build_spec(), handler)


def test_registry_rejects_disabled_agent() -> None:
    registry = AgentRegistry()
    registry.register(build_spec(enabled=False), handler)
    task = AgentTask(assigned_to="web_research", objective="Research")

    with pytest.raises(ValueError, match="disabled"):
        registry.validate_task(task)


def test_registry_rejects_unauthorized_tool() -> None:
    registry = AgentRegistry()
    registry.register(build_spec(), handler)
    task = AgentTask(
        assigned_to="web_research",
        objective="Research",
        allowed_tools=["smtp_send"],
    )

    with pytest.raises(ValueError, match="cannot use tools"):
        registry.validate_task(task)
