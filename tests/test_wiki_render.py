from pmaa.ui.wiki_render import build_wiki_graph_html
from pmaa.wiki.importer import WikiGraph, WikiGraphEdge, WikiGraphNode


def test_build_wiki_graph_html_renders_nodes_and_edges():
    graph = WikiGraph(
        nodes=[
            WikiGraphNode("file:notes.md", "notes.md", "file"),
            WikiGraphNode("wiki/imports/notes/index", "Notes", "page"),
        ],
        edges=[
            WikiGraphEdge(
                source="file:notes.md",
                target="wiki/imports/notes/index",
                edge_type="generates",
            )
        ],
    )

    html = build_wiki_graph_html(graph)

    assert "<svg" in html
    assert "notes.md" in html
    assert "Notes" in html
    assert "line" in html
    assert "wiki-node-page" in html
    assert 'href="#wiki-edge-0"' in html
    assert "wiki-edge-detail" in html


def test_build_wiki_graph_html_expands_large_graph():
    graph = WikiGraph(
        nodes=[WikiGraphNode("file:big.md", "big.md", "file")]
        + [
            WikiGraphNode(f"wiki/imports/big/page-{index}", f"Page {index}", "section")
            for index in range(286)
        ],
        edges=[
            WikiGraphEdge("file:big.md", f"wiki/imports/big/page-{index}", "generates")
            for index in range(286)
        ],
    )

    html = build_wiki_graph_html(graph)

    assert 'viewBox="0 0 1780 1312"' in html
    assert "点击连线查看关系详情" in html
