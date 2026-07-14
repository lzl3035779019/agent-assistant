import sys
from pathlib import Path

from pmaa.tools.mcp_client import MCPClient, MCPServerConfig


def test_mcp_stdio_client_lists_tools_and_calls_tool():
    server_path = Path(__file__).parent / "fake_gbrain_mcp_server.py"
    client = MCPClient(
        MCPServerConfig(
            transport="stdio",
            command=sys.executable,
            args=[str(server_path)],
            cwd=Path.cwd(),
        )
    )

    tools = client.list_tools()
    result = client.call_tool("search", {"query": "LangGraph", "limit": 2})

    assert any(tool.name == "search" for tool in tools.tools)
    assert "LangGraph:2" in result.content[0].text


def test_mcp_sse_config_requires_url():
    client = MCPClient(MCPServerConfig(transport="sse"))

    try:
        client.list_tools()
    except Exception as exc:
        assert "url is required" in str(exc)
    else:
        raise AssertionError("Expected SSE url validation error.")


def test_mcp_http_config_requires_url():
    client = MCPClient(MCPServerConfig(transport="http"))

    try:
        client.list_tools()
    except Exception as exc:
        assert "url is required" in str(exc)
    else:
        raise AssertionError("Expected HTTP url validation error.")
