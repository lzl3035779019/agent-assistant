import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pmaa.config import load_settings
from pmaa.schemas.task import Source
from pmaa.tools.mcp_client import MCPClient, MCPServerConfig


DEFAULT_GBRAIN_INBOX_DIR = r"C:\Users\lzl\GbrainInbox"
DEFAULT_WIKI_TOOLS = {
    "preview": "wiki_import_preview",
    "commit": "wiki_import_commit",
    "status": "wiki_import_status",
    "search": "wiki_search",
    "get_page": "wiki_get_page",
    "visualize": "wiki_visualize",
    "overview": "wiki_overview",
    "delete_source": "wiki_delete_source",
}


@dataclass(frozen=True)
class WikiPage:
    slug: str
    title: str
    content: str = ""
    source_filename: str = ""
    action: str = "preview"
    reason: str = ""


@dataclass(frozen=True)
class WikiGraphNode:
    node_id: str
    label: str
    node_type: str
    highlighted: bool = False


@dataclass(frozen=True)
class WikiGraphEdge:
    source: str
    target: str
    edge_type: str


@dataclass(frozen=True)
class WikiGraph:
    nodes: list[WikiGraphNode]
    edges: list[WikiGraphEdge]


@dataclass(frozen=True)
class WikiImportPreview:
    import_id: str
    original_filename: str
    safe_filename: str
    raw_data: bytes
    inbox_path: Path
    mcp_file_path: str
    root_slug: str
    pages: list[WikiPage]
    graph: WikiGraph
    summary: str = ""
    status: str = "preview"
    raw_payload: Any = None


@dataclass(frozen=True)
class WikiImportResult:
    import_id: str
    root_slug: str
    page_count: int
    written_slugs: list[str]
    status: str
    raw_payload: Any = None


@dataclass(frozen=True)
class WikiDeleteResult:
    source_slug: str
    status: str
    deleted_slugs: list[str]
    deleted_edges: int = 0
    raw_payload: Any = None


@dataclass(frozen=True)
class WikiPageSummary:
    slug: str
    title: str
    updated_at: str = ""


@dataclass(frozen=True)
class PreparedWikiFile:
    original_filename: str
    safe_filename: str
    raw_data: bytes
    inbox_path: Path
    mcp_file_path: str


class GBrainWikiToolUnavailable(RuntimeError):
    pass


class GBrainWikiService:
    def __init__(
        self,
        client: MCPClient,
        inbox_dir: str | Path,
        native_client: MCPClient | None = None,
    ) -> None:
        self._client = client
        self._inbox_dir = Path(inbox_dir)
        self._native_client = native_client

    def available_tools(self) -> set[str]:
        result = self._client.list_tools()
        return {tool.name for tool in getattr(result, "tools", [])}

    def has_high_level_tools(self) -> bool:
        tools = self.available_tools()
        required = {
            DEFAULT_WIKI_TOOLS["preview"],
            DEFAULT_WIKI_TOOLS["commit"],
            DEFAULT_WIKI_TOOLS["search"],
            DEFAULT_WIKI_TOOLS["get_page"],
            DEFAULT_WIKI_TOOLS["visualize"],
            DEFAULT_WIKI_TOOLS["overview"],
        }
        return required.issubset(tools)

    def prepare_file(self, filename: str, data: bytes) -> PreparedWikiFile:
        safe_filename = _safe_filename(filename, data)
        inbox_path = self._inbox_dir / safe_filename
        return PreparedWikiFile(
            original_filename=filename,
            safe_filename=safe_filename,
            raw_data=data,
            inbox_path=inbox_path,
            mcp_file_path=_to_mcp_file_path(inbox_path),
        )

    def save_uploaded_file(self, prepared_file: PreparedWikiFile) -> None:
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        prepared_file.inbox_path.write_bytes(prepared_file.raw_data)

    def import_preview(
        self,
        filename: str,
        data: bytes,
        title: str | None = None,
    ) -> WikiImportPreview:
        prepared_file = self.prepare_file(filename, data)
        self.save_uploaded_file(prepared_file)
        arguments: dict[str, Any] = {"path": prepared_file.mcp_file_path}
        if title:
            arguments["title"] = title
        result = self._client.call_tool(DEFAULT_WIKI_TOOLS["preview"], arguments)
        preview = parse_import_preview(_extract_payload(result), prepared_file)
        if not preview.import_id:
            raise RuntimeError(
                "GBrain 返回了空的导入预览。请重试；若问题持续，请检查 MCP 返回格式。"
            )
        return preview

    def import_commit(self, import_id: str) -> WikiImportResult:
        result = self._client.call_tool(
            DEFAULT_WIKI_TOOLS["commit"],
            {"import_id": import_id},
        )
        return parse_import_result(_extract_payload(result))

    def import_status(self, import_id: str) -> dict[str, Any]:
        result = self._client.call_tool(
            DEFAULT_WIKI_TOOLS["status"],
            {"import_id": import_id},
        )
        payload = _extract_payload(result)
        return payload if isinstance(payload, dict) else {"status": str(payload)}

    def search(self, query: str, limit: int = 5) -> list[Source]:
        result = self._client.call_tool(
            DEFAULT_WIKI_TOOLS["search"],
            {"query": query, "limit": limit},
        )
        return parse_wiki_sources(_extract_payload(result))

    def get_page(self, slug: str) -> Source:
        result = self._client.call_tool(DEFAULT_WIKI_TOOLS["get_page"], {"slug": slug})
        sources = parse_wiki_sources(_extract_payload(result))
        if sources:
            return sources[0]
        return Source(title=slug, url=f"gbrain://page/{slug}", snippet="")

    def visualize(self, root_slug: str, depth: int = 2) -> WikiGraph:
        result = self._client.call_tool(
            DEFAULT_WIKI_TOOLS["visualize"],
            {"root_slug": root_slug, "depth": depth},
        )
        return parse_graph(_extract_payload(result))

    def overview(self, limit: int = 200) -> WikiGraph:
        result = self._client.call_tool(
            DEFAULT_WIKI_TOOLS["overview"],
            {"limit": limit},
        )
        return parse_graph(_extract_payload(result))

    def delete_source(self, source_slug: str) -> WikiDeleteResult:
        if not source_slug.startswith("sources/"):
            raise ValueError("只允许删除 GBrain 原始来源页（sources/...）。")
        tools = self.available_tools()
        delete_tool = DEFAULT_WIKI_TOOLS["delete_source"]
        if delete_tool in tools:
            result = self._client.call_tool(delete_tool, {"source_slug": source_slug})
            return parse_delete_result(_extract_payload(result), source_slug)
        return self._delete_source_with_native_tools(source_slug)

    def _delete_source_with_native_tools(self, source_slug: str) -> WikiDeleteResult:
        client = self._get_native_client()
        tools = _tool_names(client)
        required_tools = {"list_pages", "get_page", "delete_page"}
        missing = sorted(required_tools - tools)
        if missing:
            raise GBrainWikiToolUnavailable(
                "GBrain Wiki bridge 未暴露 wiki_delete_source，且原生 GBrain MCP "
                f"缺少删除回退工具：{', '.join(missing)}。"
            )

        semantic_slugs = _semantic_page_slugs_for_source(client, source_slug)
        deleted_edges = 0
        if "remove_link" in tools:
            for slug in semantic_slugs:
                try:
                    client.call_tool("remove_link", {"from": source_slug, "to": slug})
                    deleted_edges += 1
                except Exception:
                    pass

        deleted_slugs: list[str] = []
        for slug in semantic_slugs:
            client.call_tool("delete_page", {"slug": slug})
            deleted_slugs.append(slug)
        client.call_tool("delete_page", {"slug": source_slug})
        deleted_slugs.append(source_slug)

        source_remove_payload: Any = None
        if "sources_remove" in tools:
            try:
                source_remove_payload = _extract_payload(
                    client.call_tool(
                        "sources_remove",
                        {
                            "id": _source_id_from_slug(source_slug),
                            "confirm_destructive": True,
                        },
                    )
                )
            except Exception as exc:
                source_remove_payload = {"warning": str(exc)}

        return WikiDeleteResult(
            source_slug=source_slug,
            status="deleted",
            deleted_slugs=deleted_slugs,
            deleted_edges=deleted_edges,
            raw_payload={
                "mode": "native_fallback",
                "source_remove": source_remove_payload,
            },
        )

    def _get_native_client(self) -> MCPClient:
        if self._native_client is None:
            self._native_client = _create_native_client()
        return self._native_client


def create_gbrain_wiki_service() -> GBrainWikiService:
    current_settings = load_settings()
    # The upload bridge is intentionally separate from the native GBrain MCP
    # connection used by the Knowledge Agent.  It only adapts Windows files to
    # `gbrain capture --file`; all querying and page operations stay native.
    config = MCPServerConfig(
        transport="stdio",
        command=current_settings.gbrain_wiki_bridge_command,
        args=current_settings.gbrain_wiki_bridge_args,
    )
    return GBrainWikiService(MCPClient(config), inbox_dir=get_gbrain_inbox_dir(current_settings))


def _create_native_client() -> MCPClient:
    settings = load_settings()
    return MCPClient(
        MCPServerConfig(
            transport=settings.gbrain_mcp_transport,  # type: ignore[arg-type]
            command=settings.gbrain_mcp_command,
            args=settings.gbrain_mcp_args,
            url=settings.gbrain_mcp_url,
        )
    )


def parse_import_preview(payload: Any, prepared_file: PreparedWikiFile) -> WikiImportPreview:
    payload = _unwrap_result(payload)
    data = payload if isinstance(payload, dict) else {}
    pages = [_page_from_item(item, prepared_file.safe_filename) for item in _items(data, "pages")]
    graph = parse_graph(data)
    root_slug = str(data.get("root_slug") or data.get("rootSlug") or _first_page_slug(pages))
    return WikiImportPreview(
        import_id=str(data.get("import_id") or data.get("importId") or ""),
        original_filename=prepared_file.original_filename,
        safe_filename=prepared_file.safe_filename,
        raw_data=prepared_file.raw_data,
        inbox_path=prepared_file.inbox_path,
        mcp_file_path=prepared_file.mcp_file_path,
        root_slug=root_slug,
        pages=pages,
        graph=graph,
        summary=str(data.get("summary") or data.get("message") or ""),
        status=str(data.get("status") or "preview"),
        raw_payload=payload,
    )


def parse_import_result(payload: Any) -> WikiImportResult:
    payload = _unwrap_result(payload)
    data = payload if isinstance(payload, dict) else {}
    pages = _items(data, "pages")
    written_slugs = [
        str(item.get("slug") or item.get("id"))
        for item in pages
        if isinstance(item, dict) and (item.get("slug") or item.get("id"))
    ]
    return WikiImportResult(
        import_id=str(data.get("import_id") or data.get("importId") or ""),
        root_slug=str(data.get("root_slug") or data.get("rootSlug") or ""),
        page_count=int(data.get("page_count") or data.get("pageCount") or len(written_slugs)),
        written_slugs=written_slugs,
        status=str(data.get("status") or "committed"),
        raw_payload=payload,
    )


def parse_delete_result(payload: Any, source_slug: str) -> WikiDeleteResult:
    payload = _unwrap_result(payload)
    data = payload if isinstance(payload, dict) else {}
    deleted_items = data.get("deleted_slugs") or data.get("deletedSlugs") or data.get("pages") or []
    deleted_slugs = [
        str(item.get("slug") or item.get("id"))
        if isinstance(item, dict)
        else str(item)
        for item in deleted_items
        if (isinstance(item, dict) and (item.get("slug") or item.get("id"))) or str(item)
    ]
    return WikiDeleteResult(
        source_slug=str(data.get("source_slug") or data.get("sourceSlug") or source_slug),
        status=str(data.get("status") or "deleted"),
        deleted_slugs=deleted_slugs,
        deleted_edges=int(data.get("deleted_edges") or data.get("deletedEdges") or 0),
        raw_payload=payload,
    )


def parse_graph(payload: Any) -> WikiGraph:
    payload = _unwrap_result(payload)
    data = payload if isinstance(payload, dict) else {}
    node_items = _items(data, "nodes")
    edge_items = _items(data, "edges")
    if not edge_items:
        edge_items = _items(data, "links")
    nodes = [
        WikiGraphNode(
            node_id=str(item.get("id") or item.get("slug") or item.get("node_id")),
            label=str(item.get("label") or item.get("title") or item.get("name") or item.get("slug") or item.get("id")),
            node_type=str(item.get("type") or item.get("node_type") or "page"),
            highlighted=bool(item.get("highlighted", False)),
        )
        for item in node_items
        if isinstance(item, dict)
    ]
    edges = [
        WikiGraphEdge(
            source=str(item.get("source") or item.get("from")),
            target=str(item.get("target") or item.get("to")),
            edge_type=str(item.get("type") or item.get("edge_type") or "link"),
        )
        for item in edge_items
        if isinstance(item, dict)
    ]
    return WikiGraph(nodes=nodes, edges=edges)


def parse_wiki_sources(payload: Any) -> list[Source]:
    payload = _unwrap_result(payload)
    items = _items(payload, "results") or _items(payload, "pages") or _items(payload, "items")
    if isinstance(payload, dict) and not items:
        items = [payload]
    sources: list[Source] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            sources.append(Source(title=f"Wiki result {index}", url=f"gbrain://wiki/{index}", snippet=str(item)))
            continue
        slug = str(item.get("slug") or item.get("id") or index)
        sources.append(
            Source(
                title=str(item.get("title") or item.get("name") or slug),
                url=str(item.get("url") or item.get("uri") or f"gbrain://page/{slug}"),
                snippet=str(item.get("snippet") or item.get("content") or item.get("text") or item.get("summary") or ""),
            )
        )
    return sources


def _tool_names(client: MCPClient) -> set[str]:
    result = client.list_tools()
    return {tool.name for tool in getattr(result, "tools", [])}


def _semantic_page_slugs_for_source(client: MCPClient, source_slug: str) -> list[str]:
    payload = _extract_payload(client.call_tool("list_pages", {"limit": 10000}))
    slugs = [
        str(item.get("slug") or item.get("id") or "")
        for item in _items(payload, "pages")
        if isinstance(item, dict) and (item.get("slug") or item.get("id"))
    ]
    matched: list[str] = []
    for slug in slugs:
        if slug == source_slug:
            continue
        page_payload = _extract_payload(client.call_tool("get_page", {"slug": slug}))
        content = _page_content(page_payload)
        if (
            _frontmatter_value(content, "managed_by") == "semantic-knowledge-model"
            and _frontmatter_value(content, "source_slug") == source_slug
        ):
            matched.append(slug)
    return matched


def _page_content(payload: Any) -> str:
    payload = _unwrap_result(payload)
    if isinstance(payload, dict):
        return str(payload.get("content") or payload.get("text") or payload.get("body") or "")
    return str(payload)


def _frontmatter_value(content: str, key: str) -> str:
    prefix = f"{key}:"
    for line in content.splitlines():
        text = line.strip()
        if text.startswith(prefix):
            return text[len(prefix) :].strip().strip("\"'")
    return ""


def _source_id_from_slug(source_slug: str) -> str:
    return source_slug.rstrip("/").split("/")[-1]


def is_gbrain_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "gbrain_mcp_enabled", False))


def get_gbrain_inbox_dir(settings: Any) -> str:
    return str(getattr(settings, "gbrain_inbox_dir", DEFAULT_GBRAIN_INBOX_DIR))


def _page_from_item(item: Any, safe_filename: str) -> WikiPage:
    if not isinstance(item, dict):
        text = str(item)
        return WikiPage(slug=text, title=text, source_filename=safe_filename)
    return WikiPage(
        slug=str(item.get("slug") or item.get("id") or ""),
        title=str(item.get("title") or item.get("name") or item.get("slug") or ""),
        content=str(item.get("content") or item.get("snippet") or item.get("summary") or ""),
        source_filename=safe_filename,
        action=str(item.get("action") or item.get("operation") or "preview"),
        reason=str(item.get("reason") or item.get("note") or ""),
    )


def _safe_filename(filename: str, data: bytes) -> str:
    path = Path(filename)
    stem = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in path.stem).strip("-")
    stem = stem.lower() or "upload"
    digest = hashlib.sha1(data).hexdigest()[:8]
    return f"{stem[:80]}-{digest}{path.suffix.lower()}"


def _to_mcp_file_path(path: Path) -> str:
    absolute = path.resolve()
    drive = absolute.drive.rstrip(":").lower()
    if drive:
        return f"/mnt/{drive}/" + "/".join(absolute.parts[1:])
    return str(absolute).replace("\\", "/")


def _extract_payload(result: Any) -> Any:
    # Different MCP Python client versions may expose CallToolResult as either
    # a Pydantic object or a plain mapping. Support both representations so a
    # valid text response cannot silently turn into an empty Wiki preview.
    if isinstance(result, dict):
        structured_content = result.get("structuredContent") or result.get("structured_content")
        if structured_content:
            return _loads_if_json(structured_content)
        content = result.get("content", [])
        if content:
            first = content[0]
            text = first.get("text", "") if isinstance(first, dict) else getattr(first, "text", "")
            return _loads_if_json(text)
        return _loads_if_json(result)
    structured_content = getattr(result, "structuredContent", None)
    if structured_content:
        return _loads_if_json(structured_content)
    content = getattr(result, "content", [])
    if content:
        return _loads_if_json(getattr(content[0], "text", ""))
    return _loads_if_json(result)


def _unwrap_result(payload: Any) -> Any:
    payload = _loads_if_json(payload)
    if isinstance(payload, dict) and "result" in payload:
        return _loads_if_json(payload["result"])
    return payload


def _items(payload: Any, key: str) -> list[Any]:
    payload = _unwrap_result(payload)
    if isinstance(payload, dict):
        value = payload.get(key)
        return value if isinstance(value, list) else []
    if isinstance(payload, list):
        return payload
    return []


def _loads_if_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _first_page_slug(pages: list[WikiPage]) -> str:
    return pages[0].slug if pages else ""
