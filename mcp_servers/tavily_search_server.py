import json

from mcp.server.fastmcp import FastMCP

from pmaa.config import settings
from pmaa.tools.tavily_search import TavilySearchClient


mcp = FastMCP("pmaa-tavily-search")


@mcp.tool()
def web_search(query: str, max_results: int | None = None) -> str:
    """Search the public web with Tavily and return normalized sources."""
    client = TavilySearchClient(
        api_key=settings.tavily_api_key,
        base_url=settings.tavily_base_url,
    )
    sources = client.search(query, max_results=max_results or settings.tavily_max_results)
    return json.dumps([source.model_dump() for source in sources], ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
