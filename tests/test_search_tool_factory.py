import pytest
import sys
from pathlib import Path

from pmaa.config import Settings
from pmaa.schemas.task import Source
import pmaa.tools.factory as tool_factory
from pmaa.tools.mcp_search import MCPStdioSearchTool
from pmaa.tools.factory import (
    SearchToolConfigurationError,
    create_knowledge_tool,
    create_search_tool,
    create_wiki_get_page_tool,
)


def test_factory_creates_mcp_backed_tavily_search_tool():
    tool = create_search_tool(
        provider="tavily_mcp",
        tavily_api_key="test-key",
        mcp_search_callable=lambda query, max_results: [
            Source(title="Result", url="https://example.com", snippet=f"{query}:{max_results}")
        ],
        tavily_max_results=4,
    )

    assert tool("LangGraph") == [
        Source(title="Result", url="https://example.com", snippet="LangGraph:4")
    ]


def test_factory_rejects_tavily_provider_without_key():
    with pytest.raises(SearchToolConfigurationError):
        create_search_tool(provider="tavily_mcp", tavily_api_key="")


def test_mcp_stdio_search_tool_calls_mcp_server():
    server_path = Path(__file__).parent / "fake_mcp_search_server.py"
    tool = MCPStdioSearchTool(
        max_results=2,
        command=sys.executable,
        args=[str(server_path)],
        cwd=Path.cwd(),
    )

    assert tool("LangGraph") == [
        Source(
            title="Fake result",
            url="https://example.com/fake",
            snippet="LangGraph:2",
        )
    ]


def test_factory_skips_knowledge_tool_when_gbrain_disabled():
    assert create_knowledge_tool(enabled=False) is None


def test_factory_creates_gbrain_knowledge_tool_with_injected_client(monkeypatch):
    class FakeMCPClient:
        def call_tool(self, name, arguments):
            return {
                "results": [
                    {
                        "title": name,
                        "url": "gbrain://page/factory",
                        "content": f"{arguments['query']}:{arguments['limit']}",
                    }
                ]
            }

    monkeypatch.setattr(
        tool_factory,
        "load_settings",
        lambda: Settings(
            gbrain_mcp_enabled=True,
            gbrain_mcp_search_tool="search",
            gbrain_mcp_max_results=3,
        ),
    )

    tool = create_knowledge_tool(mcp_client=FakeMCPClient())

    assert tool is not None
    assert tool("wiki") == [
        Source(title="search", url="gbrain://page/factory", snippet="wiki:3")
    ]


def test_factory_creates_wiki_get_page_tool_with_injected_client(monkeypatch):
    class FakeMCPClient:
        def call_tool(self, name, arguments):
            return {
                "slug": arguments["slug"],
                "title": name,
                "content": "Full page content",
            }

    monkeypatch.setattr(
        tool_factory,
        "load_settings",
        lambda: Settings(gbrain_mcp_enabled=True),
    )

    tool = create_wiki_get_page_tool(mcp_client=FakeMCPClient())

    assert tool is not None
    assert tool("wiki/documents/pmaa/index") == [
        Source(
            title="wiki_get_page",
            url="gbrain://page/wiki/documents/pmaa/index",
            snippet="Full page content",
        )
    ]
