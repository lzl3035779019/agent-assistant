import sys
import json
from pathlib import Path
from types import SimpleNamespace

from pmaa.tools.mcp_client import MCPClient, MCPServerConfig
from pmaa.wiki.importer import (
    DEFAULT_GBRAIN_INBOX_DIR,
    GBrainWikiService,
    get_gbrain_inbox_dir,
    is_gbrain_enabled,
    parse_graph,
)


def _service(tmp_path: Path) -> GBrainWikiService:
    server_path = Path(__file__).parent / "fake_gbrain_mcp_server.py"
    return GBrainWikiService(
        MCPClient(
            MCPServerConfig(
                transport="stdio",
                command=sys.executable,
                args=[str(server_path)],
                cwd=Path.cwd(),
            )
        ),
        inbox_dir=tmp_path,
    )


def test_gbrain_wiki_service_detects_high_level_tools(tmp_path):
    service = _service(tmp_path)

    assert service.has_high_level_tools() is True


def test_gbrain_wiki_service_calls_high_level_preview_and_saves_file(tmp_path):
    service = _service(tmp_path)

    preview = service.import_preview(
        filename="PMAA Notes.pdf",
        data=b"fake pdf bytes",
        title="PMAA Notes",
    )

    assert preview.import_id == "import-123"
    assert preview.safe_filename.endswith(".pdf")
    assert preview.inbox_path.exists()
    assert preview.mcp_file_path.startswith("/mnt/")
    assert preview.pages[0].slug == "concepts/pmaa"
    assert preview.pages[0].action == "create"
    assert preview.graph.edges[0].edge_type == "uses"
    assert "Preview generated" in preview.summary


def test_gbrain_wiki_service_accepts_dictionary_mcp_result(tmp_path):
    class DictionaryClient:
        def call_tool(self, name, arguments):
            assert name == "wiki_import_preview"
            assert arguments["path"].startswith("/mnt/")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "import_id": "dictionary-result",
                                "root_slug": "sources/demo",
                                "pages": [{"slug": "wiki/demo", "title": "Demo"}],
                                "nodes": [{"id": "wiki/demo", "label": "Demo", "type": "concept"}],
                                "edges": [],
                            }
                        ),
                    }
                ]
            }

    service = GBrainWikiService(DictionaryClient(), inbox_dir=tmp_path)
    preview = service.import_preview("Demo.md", b"# Demo")

    assert preview.import_id == "dictionary-result"
    assert preview.pages[0].slug == "wiki/demo"


def test_gbrain_wiki_service_commits_preview_by_import_id(tmp_path):
    service = _service(tmp_path)

    result = service.import_commit("import-123")

    assert result.import_id == "import-123"
    assert result.status == "committed"
    assert result.page_count == 2
    assert result.written_slugs == ["concepts/pmaa", "methods/langgraph"]


def test_gbrain_wiki_service_deletes_source_and_related_pages(tmp_path):
    service = _service(tmp_path)

    result = service.delete_source("sources/documents/source-1")

    assert result.status == "deleted"
    assert result.source_slug == "sources/documents/source-1"
    assert result.deleted_slugs == [
        "sources/documents/source-1",
        "wiki/concept/from-source",
        "wiki/method/from-source",
    ]
    assert result.deleted_edges == 4


def test_gbrain_wiki_service_falls_back_to_native_delete_when_bridge_has_no_delete_tool(tmp_path):
    class BridgeClientWithoutDelete:
        def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(name="wiki_import_preview"),
                    SimpleNamespace(name="wiki_import_commit"),
                    SimpleNamespace(name="wiki_search"),
                    SimpleNamespace(name="wiki_get_page"),
                    SimpleNamespace(name="wiki_visualize"),
                    SimpleNamespace(name="wiki_overview"),
                ]
            )

        def call_tool(self, name, arguments):
            raise AssertionError(f"unexpected bridge call: {name}")

    class NativeDeleteClient:
        def __init__(self):
            self.calls = []

        def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(name="list_pages"),
                    SimpleNamespace(name="get_page"),
                    SimpleNamespace(name="delete_page"),
                    SimpleNamespace(name="remove_link"),
                    SimpleNamespace(name="sources_remove"),
                ]
            )

        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            if name == "list_pages":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "pages": [
                                        {"slug": "wiki/concept/from-source"},
                                        {"slug": "wiki/concept/shared"},
                                    ]
                                }
                            ),
                        }
                    ]
                }
            if name == "get_page":
                content = {
                    "wiki/concept/from-source": (
                        "---\n"
                        "managed_by: semantic-knowledge-model\n"
                        "source_slug: sources/documents/source-1\n"
                        "---\n"
                    ),
                    "wiki/concept/shared": (
                        "---\n"
                        "managed_by: semantic-knowledge-model\n"
                        "source_slug: sources/documents/other\n"
                        "---\n"
                    ),
                }[arguments["slug"]]
                return {"content": [{"type": "text", "text": json.dumps({"content": content})}]}
            return {"content": [{"type": "text", "text": json.dumps({"ok": True})}]}

    native_client = NativeDeleteClient()
    service = GBrainWikiService(
        BridgeClientWithoutDelete(),
        inbox_dir=tmp_path,
        native_client=native_client,
    )

    result = service.delete_source("sources/documents/source-1")

    assert result.status == "deleted"
    assert result.deleted_slugs == [
        "wiki/concept/from-source",
        "sources/documents/source-1",
    ]
    assert ("delete_page", {"slug": "wiki/concept/from-source"}) in native_client.calls
    assert ("delete_page", {"slug": "sources/documents/source-1"}) in native_client.calls
    assert ("delete_page", {"slug": "wiki/concept/shared"}) not in native_client.calls
    assert (
        "sources_remove",
        {"id": "source-1", "confirm_destructive": True},
    ) in native_client.calls


def test_gbrain_wiki_service_search_get_page_and_visualize(tmp_path):
    service = _service(tmp_path)

    sources = service.search("Agentic RAG")
    page = service.get_page("concepts/pmaa")
    graph = service.visualize("concepts/pmaa")

    assert sources[0].title == "PMAA"
    assert "Agentic RAG" in sources[0].snippet
    assert page.url == "gbrain://page/concepts/pmaa"
    assert graph.nodes[0].node_id == "concepts/pmaa"
    assert graph.edges[0].edge_type == "uses"


def test_parse_graph_accepts_links_alias():
    graph = parse_graph(
        {
            "nodes": [{"id": "a", "label": "A", "type": "concept"}],
            "links": [{"from": "a", "to": "b", "type": "relates"}],
        }
    )

    assert graph.nodes[0].label == "A"
    assert graph.edges[0].source == "a"
    assert graph.edges[0].target == "b"


def test_gbrain_setting_helpers_tolerate_old_settings_object():
    class OldSettings:
        pass

    settings = OldSettings()

    assert is_gbrain_enabled(settings) is False
    assert get_gbrain_inbox_dir(settings) == DEFAULT_GBRAIN_INBOX_DIR
