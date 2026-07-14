import pytest

from pmaa.agents.tool import ToolAgent
from pmaa.tools.registry import ToolRegistry


def test_tool_agent_invokes_registered_tool():
    registry = ToolRegistry()
    registry.register("echo", lambda text: f"echo:{text}")
    agent = ToolAgent(registry)

    result = agent.invoke("echo", "LangGraph")

    assert result == "echo:LangGraph"


def test_tool_agent_rejects_missing_tool():
    agent = ToolAgent(ToolRegistry())

    with pytest.raises(KeyError):
        agent.invoke("missing", "LangGraph")
