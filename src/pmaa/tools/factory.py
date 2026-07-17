from collections.abc import Callable

from pmaa.config import load_settings, settings
from pmaa.schemas.task import Source
from pmaa.tools.email_tool import EmailTool
from pmaa.tools.gbrain import GBrainGetPageTool, GBrainKnowledgeTool
from pmaa.tools.mcp_client import MCPClient, MCPServerConfig
from pmaa.tools.mcp_search import CallableSearchTool, MCPStdioSearchTool
from pmaa.tools.search_tool import mock_search


SearchTool = Callable[[str], list[Source]]


class SearchToolConfigurationError(RuntimeError):
    pass


class KnowledgeToolConfigurationError(RuntimeError):
    pass


def create_search_tool(
    provider: str | None = None,
    tavily_api_key: str | None = None,
    tavily_max_results: int | None = None,
    mcp_search_callable: Callable[[str, int], list[Source]] | None = None,
) -> SearchTool:
    current_settings = load_settings() if provider is None else settings
    active_provider = (provider or current_settings.search_provider).lower()
    api_key = tavily_api_key if tavily_api_key is not None else current_settings.tavily_api_key
    max_results = tavily_max_results or current_settings.tavily_max_results

    if active_provider in {"tavily", "tavily_mcp"}:
        if not api_key:
            raise SearchToolConfigurationError(
                "SEARCH_PROVIDER is tavily_mcp, but TAVILY_API_KEY is missing."
            )
        if mcp_search_callable is not None:
            return CallableSearchTool(mcp_search_callable, max_results)
        return MCPStdioSearchTool(max_results=max_results)

    return mock_search


def create_knowledge_tool(
    enabled: bool | None = None,
    mcp_client: MCPClient | None = None,
) -> SearchTool | None:
    current_settings = load_settings()
    active_enabled = current_settings.gbrain_mcp_enabled if enabled is None else enabled
    if not active_enabled:
        return None
    if mcp_client is None:
        transport = current_settings.gbrain_mcp_transport
        if transport not in {"stdio", "sse", "http"}:
            raise KnowledgeToolConfigurationError(
                f"Unsupported GBRAIN_MCP_TRANSPORT: {transport}"
            )
        if transport == "stdio":
            config = MCPServerConfig(
                transport="stdio",
                command=current_settings.gbrain_mcp_command,
                args=current_settings.gbrain_mcp_args,
            )
        else:
            if not current_settings.gbrain_mcp_url:
                raise KnowledgeToolConfigurationError(
                    "GBRAIN_MCP_URL is required for sse/http transport."
                )
            config = MCPServerConfig(
                transport=transport,
                url=current_settings.gbrain_mcp_url,
            )
        mcp_client = MCPClient(config)
    return GBrainKnowledgeTool(
        mcp_client,
        search_tool_name=current_settings.gbrain_mcp_search_tool,
        max_results=current_settings.gbrain_mcp_max_results,
    )


def create_wiki_get_page_tool(
    enabled: bool | None = None,
    mcp_client: MCPClient | None = None,
) -> SearchTool | None:
    current_settings = load_settings()
    active_enabled = current_settings.gbrain_mcp_enabled if enabled is None else enabled
    if not active_enabled:
        return None
    if mcp_client is None:
        transport = current_settings.gbrain_mcp_transport
        if transport not in {"stdio", "sse", "http"}:
            raise KnowledgeToolConfigurationError(
                f"Unsupported GBRAIN_MCP_TRANSPORT: {transport}"
            )
        if transport == "stdio":
            config = MCPServerConfig(
                transport="stdio",
                command=current_settings.gbrain_mcp_command,
                args=current_settings.gbrain_mcp_args,
            )
        else:
            if not current_settings.gbrain_mcp_url:
                raise KnowledgeToolConfigurationError(
                    "GBRAIN_MCP_URL is required for sse/http transport."
                )
            config = MCPServerConfig(
                transport=transport,
                url=current_settings.gbrain_mcp_url,
            )
        mcp_client = MCPClient(config)
    return GBrainGetPageTool(
        mcp_client,
        get_page_tool_name=current_settings.gbrain_mcp_get_page_tool,
    )


def create_email_tool() -> EmailTool:
    return EmailTool()
