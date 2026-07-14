import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pmaa.schemas.task import Source
from pmaa.tools.mcp_client import MCPClient, MCPServerConfig


class MCPStdioSearchTool:
    def __init__(
        self,
        max_results: int = 5,
        command: str | None = None,
        args: list[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._max_results = max_results
        self._client = MCPClient(
            MCPServerConfig(
                transport="stdio",
                command=command or sys.executable,
                args=args or ["-m", "mcp_servers.tavily_search_server"],
                cwd=cwd or Path.cwd(),
                env=env or os.environ.copy(),
            )
        )

    def __call__(self, query: str) -> list[Source]:
        result = self._client.call_tool(
            "web_search",
            {"query": query, "max_results": self._max_results},
        )
        return self._parse_sources(result)

    def _parse_sources(self, result: Any) -> list[Source]:
        structured_content = getattr(result, "structuredContent", None)
        if structured_content:
            if isinstance(structured_content, dict) and "result" in structured_content:
                payload = json.loads(structured_content["result"])
                return [Source.model_validate(item) for item in payload]
            if isinstance(structured_content, list):
                return [Source.model_validate(item) for item in structured_content]

        content = getattr(result, "content", [])
        if not content:
            return []

        text = getattr(content[0], "text", "[]")
        payload = json.loads(text)
        return [Source.model_validate(item) for item in payload]


class CallableSearchTool:
    def __init__(
        self,
        search_callable: Callable[[str, int], list[Source]],
        max_results: int,
    ) -> None:
        self._search_callable = search_callable
        self._max_results = max_results

    def __call__(self, query: str) -> list[Source]:
        return self._search_callable(query, self._max_results)
