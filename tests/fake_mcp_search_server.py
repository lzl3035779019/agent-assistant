import json

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("fake-search")


@mcp.tool()
def web_search(query: str, max_results: int) -> str:
    return json.dumps(
        [
            {
                "title": "Fake result",
                "url": "https://example.com/fake",
                "snippet": f"{query}:{max_results}",
            }
        ]
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
