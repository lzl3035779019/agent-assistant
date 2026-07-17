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


def test_build_wiki_graph_html_updates_details_from_node_and_edge_clicks():
    graph = WikiGraph(
        nodes=[
            WikiGraphNode("source:notes.md", "notes.md", "source"),
            WikiGraphNode("wiki/concept/rag", "RAG", "concept"),
        ],
        edges=[
            WikiGraphEdge(
                source="source:notes.md",
                target="wiki/concept/rag",
                edge_type="supports",
            )
        ],
    )

    html = build_wiki_graph_html(graph)

    assert 'data-detail-target="wiki-edge-0"' in html
    assert 'data-detail-target="wiki-node-0"' in html
    assert 'data-detail-target="wiki-node-1"' in html
    assert 'id="wiki-node-1"' in html
    assert "wiki-node-detail" in html
    assert "showDetail(targetId)" in html
    assert "addEventListener('click'" in html
    assert "event.target.closest('[data-detail-target]')" in html
    assert "is-selected" in html
    assert "trigger.classList.toggle('is-selected'" in html


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
    assert ">Page 1</text>" in html
    assert ">Page 285</text>" in html
    assert 'class="wiki-graph-toolbar"' in html
    assert 'data-action="zoom-in"' in html
    assert 'data-action="zoom-out"' in html
    assert 'data-action="reset"' in html
    assert 'data-wiki-graph-height="920"' in html
    assert "addEventListener('wheel'" in html
    assert "addEventListener('pointerdown'" in html
    assert "点击连线查看关系" in html
