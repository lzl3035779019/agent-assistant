from typing import Any

from pmaa.tools.registry import ToolRegistry


class ToolAgent:
    name = "tool"

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def invoke(self, tool_name: str, *args: Any, **kwargs: Any) -> Any:
        return self._registry.call(tool_name, *args, **kwargs)
