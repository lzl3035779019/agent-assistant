import pytest

from pmaa.tools.registry import ToolRegistry


def test_registry_returns_registered_tool_result():
    registry = ToolRegistry()
    registry.register("echo", lambda query: f"echo:{query}")

    assert registry.call("echo", "LangGraph") == "echo:LangGraph"


def test_registry_rejects_missing_tool():
    registry = ToolRegistry()

    with pytest.raises(KeyError):
        registry.call("missing", "query")
