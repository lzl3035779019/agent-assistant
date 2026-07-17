import json

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("fake-gbrain")


@mcp.tool()
def search(query: str, limit: int = 5, max_results: int = 5) -> str:
    count = limit or max_results
    return json.dumps(
        {
            "results": [
                {
                    "title": "GBrain note",
                    "url": "gbrain://page/1",
                    "content": f"{query}:{count}",
                    "score": 0.91,
                }
            ]
        }
    )


@mcp.tool()
def get_page(slug: str) -> str:
    return json.dumps(
        {
            "slug": slug,
            "title": "GBrain full page",
            "content": f"# GBrain full page\n\nFull content for {slug}",
            "updated_at": "2026-07-13T00:00:00Z",
        }
    )


@mcp.tool()
def file_upload(path: str, page_slug: str = "") -> str:
    return json.dumps(
        {
            "ok": True,
            "path": path,
            "page_slug": page_slug,
        }
    )


@mcp.tool()
def put_page(
    slug: str,
    content: str,
    source_kind: str = "put_page",
    source_uri: str = "",
    ingested_via: str = "",
) -> str:
    return json.dumps(
        {
            "ok": True,
            "slug": slug,
            "content_length": len(content),
            "source_kind": source_kind,
            "source_uri": source_uri,
            "ingested_via": ingested_via,
        }
    )


@mcp.tool()
def list_pages(limit: int = 50, sort: str = "updated_desc") -> str:
    return json.dumps(
        {
            "pages": [
                {
                    "slug": "wiki/imports/pmaa/index",
                    "title": "PMAA",
                    "updated_at": "2026-07-13T00:00:00Z",
                },
                {
                    "slug": "wiki/imports/pmaa/overview",
                    "title": "Overview",
                    "updated_at": "2026-07-13T00:00:01Z",
                },
            ][:limit],
            "sort": sort,
        }
    )


@mcp.tool()
def traverse_graph(slug: str, depth: int = 2, direction: str = "both") -> str:
    return json.dumps(
        {
            "nodes": [
                {"id": slug, "label": "PMAA", "type": "page"},
                {"id": f"{slug}/overview", "label": "Overview", "type": "section"},
            ],
            "edges": [
                {"source": slug, "target": f"{slug}/overview", "type": "contains"},
            ],
            "depth": depth,
            "direction": direction,
        }
    )


@mcp.tool()
def wiki_import_preview(path: str, title: str = "") -> str:
    return json.dumps(
        {
            "import_id": "import-123",
            "status": "preview",
            "root_slug": "concepts/pmaa",
            "summary": f"Preview generated from {path}",
            "pages": [
                {
                    "slug": "concepts/pmaa",
                    "title": title or "PMAA",
                    "action": "create",
                    "snippet": "Personal Multi-Agent Assistant",
                },
                {
                    "slug": "methods/langgraph",
                    "title": "LangGraph",
                    "action": "update",
                    "reason": "Existing page can be expanded.",
                },
            ],
            "nodes": [
                {"id": "concepts/pmaa", "label": "PMAA", "type": "concept"},
                {"id": "methods/langgraph", "label": "LangGraph", "type": "method"},
            ],
            "edges": [
                {"source": "concepts/pmaa", "target": "methods/langgraph", "type": "uses"},
            ],
        }
    )


@mcp.tool()
def wiki_import_commit(import_id: str) -> str:
    return json.dumps(
        {
            "import_id": import_id,
            "status": "committed",
            "root_slug": "concepts/pmaa",
            "page_count": 2,
            "pages": [
                {"slug": "concepts/pmaa"},
                {"slug": "methods/langgraph"},
            ],
        }
    )


@mcp.tool()
def wiki_import_status(import_id: str) -> str:
    return json.dumps({"import_id": import_id, "status": "completed", "progress": 1.0})


@mcp.tool()
def wiki_search(query: str, limit: int = 5) -> str:
    return json.dumps(
        {
            "results": [
                {
                    "slug": "concepts/pmaa",
                    "title": "PMAA",
                    "snippet": f"Matched {query}",
                }
            ][:limit]
        }
    )


@mcp.tool()
def wiki_get_page(slug: str) -> str:
    return json.dumps(
        {
            "slug": slug,
            "title": "Wiki Page",
            "content": "# Wiki Page\n\nFull wiki content.",
        }
    )


@mcp.tool()
def wiki_visualize(root_slug: str, depth: int = 2) -> str:
    return json.dumps(
        {
            "nodes": [
                {"id": root_slug, "label": "Root", "type": "concept"},
                {"id": "methods/langgraph", "label": "LangGraph", "type": "method"},
            ],
            "edges": [
                {"source": root_slug, "target": "methods/langgraph", "type": "uses"},
            ],
            "depth": depth,
        }
    )


@mcp.tool()
def wiki_overview(limit: int = 200) -> str:
    return json.dumps(
        {
            "nodes": [
                {"id": "concepts/pmaa", "label": "PMAA", "type": "concept"},
                {"id": "methods/langgraph", "label": "LangGraph", "type": "method"},
            ][:limit],
            "edges": [
                {"source": "concepts/pmaa", "target": "methods/langgraph", "type": "uses"},
            ],
        }
    )


@mcp.tool()
def wiki_delete_source(source_slug: str) -> str:
    return json.dumps(
        {
            "status": "deleted",
            "source_slug": source_slug,
            "deleted_slugs": [
                source_slug,
                "wiki/concept/from-source",
                "wiki/method/from-source",
            ],
            "deleted_edges": 4,
        }
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
