from html import escape

from pmaa.wiki.importer import WikiGraph, WikiGraphNode


NODE_COLORS = {
    "file": "#64748b",
    "source": "#64748b",
    "page": "#0f766e",
    "section": "#6366f1",
    "concept": "#2563eb",
    "method": "#0f766e",
    "project": "#7c4d9e",
}


def build_wiki_graph_html(
    graph: WikiGraph,
    width: int | None = None,
    height: int | None = None,
    highlighted_node_ids: set[str] | None = None,
) -> str:
    if not graph.nodes:
        return '<div class="wiki-empty-graph">暂无图谱数据</div>'

    canvas_width, canvas_height = _canvas_size(len(graph.nodes), width, height)
    positions = _layout_positions(graph.nodes, canvas_width, canvas_height)
    highlighted = {
        node.node_id for node in graph.nodes if node.highlighted
    } | (highlighted_node_ids or set())
    edge_lines: list[str] = []
    edge_details: list[str] = []

    for index, edge in enumerate(graph.edges):
        if edge.source not in positions or edge.target not in positions:
            continue
        x1, y1 = positions[edge.source]
        x2, y2 = positions[edge.target]
        source_label = _node_label(graph.nodes, edge.source)
        target_label = _node_label(graph.nodes, edge.target)
        edge_title = escape(f"{source_label} -> {target_label} · {edge.edge_type}")
        is_highlighted_edge = edge.source in highlighted or edge.target in highlighted
        edge_stroke = "#ef4444" if is_highlighted_edge else "#c9c4ba"
        edge_width = "1"
        edge_lines.append(
            f'<a href="#wiki-edge-{index}" class="wiki-edge-link{" wiki-edge-import" if is_highlighted_edge else ""}">'
            f"<title>{edge_title}</title>"
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{edge_stroke}" stroke-width="{edge_width}" />'
            "</a>"
        )
        edge_details.append(
            f'<div id="wiki-edge-{index}" class="wiki-edge-detail">'
            f'<div class="wiki-edge-detail-title">关系 #{index + 1} · {escape(edge.edge_type)}</div>'
            f"<div><b>源节点</b>：{escape(source_label)}</div>"
            f"<div><b>目标节点</b>：{escape(target_label)}</div>"
            f"<div><b>源 ID</b>：<code>{escape(edge.source)}</code></div>"
            f"<div><b>目标 ID</b>：<code>{escape(edge.target)}</code></div>"
            "</div>"
        )

    show_all_labels = len(graph.nodes) <= 80
    node_items = []
    for index, node in enumerate(graph.nodes):
        x, y = positions[node.node_id]
        is_highlighted = node.node_id in highlighted
        # A source is the provenance root, never a newly synthesized concept.
        # Keep it slate even after an import so the red nodes remain legible as
        # the knowledge pages produced in this modelling run.
        color = NODE_COLORS.get(node.node_type, "#475569") if node.node_type == "source" else ("#ef4444" if is_highlighted else NODE_COLORS.get(node.node_type, "#475569"))
        label = escape(_short_label(node.label))
        title = escape(f"{node.label} · {node.node_type}")
        should_show_label = show_all_labels or node.node_type == "file" or index % 12 == 0
        radius = _node_radius(node)
        node_items.append(
            f'<g class="wiki-node wiki-node-{escape(node.node_type)}{" wiki-node-highlighted" if is_highlighted else ""}">'
            f"<title>{title}</title>"
            + f'<circle class="wiki-node-core" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{color}" stroke="#fffdf8" stroke-width="1.5" />'
            + (
                f'<text x="{x + 13:.1f}" y="{y + 4:.1f}">{label}</text>'
                if should_show_label
                else ""
            )
            + (
                f'<text x="{x + 13:.1f}" y="{y - 8:.1f}" fill="#dc2626" font-size="10" font-weight="800">本次</text>'
                if is_highlighted and node.node_type != "source"
                else ""
            )
            + "</g>"
        )

    default_detail = edge_details[0] if edge_details else '<div class="wiki-edge-detail is-default">暂无关系</div>'
    return (
        '<div class="wiki-graph-card">'
        '<div class="wiki-graph-hint">点击连线查看关系详情；红色节点与“本次”标签表示本次导入涉及的页面，细红线表示其关联；节点过多时只显示部分标签，悬停可看完整名称。</div>'
        f'<svg viewBox="0 0 {canvas_width} {canvas_height}" role="img" aria-label="LLM Wiki graph">'
        + "".join(edge_lines)
        + "".join(node_items)
        + "</svg>"
        + '<div class="wiki-edge-details">'
        + default_detail
        + "".join(edge_details[1:])
        + "</div>"
        + "</div>"
    )


def _canvas_size(count: int, width: int | None, height: int | None) -> tuple[int, int]:
    if width is not None and height is not None:
        return width, height
    page_count = max(1, count - 1)
    rows = min(24, max(8, int(page_count**0.5 * 2.2)))
    cols = max(1, (page_count + rows - 1) // rows)
    return max(1180, 220 + cols * 130), max(680, 160 + rows * 44 + cols * 8)


def _layout_positions(
    nodes: list[WikiGraphNode],
    width: int,
    height: int,
) -> dict[str, tuple[float, float]]:
    if len(nodes) == 1:
        return {nodes[0].node_id: (width / 2, height / 2)}

    positions: dict[str, tuple[float, float]] = {}
    file_nodes = [node for node in nodes if node.node_type in {"file", "source"}]
    other_nodes = [node for node in nodes if node.node_type not in {"file", "source"}]
    main_file = file_nodes[0] if file_nodes else nodes[0]
    positions[main_file.node_id] = (100, height / 2)

    rows = min(24, max(8, int(max(1, len(other_nodes)) ** 0.5 * 2.2)))
    x_gap = 130
    y_gap = max(32, (height - 120) / max(1, rows - 1))
    for index, node in enumerate(other_nodes):
        col = index // rows
        row = index % rows
        positions[node.node_id] = (260 + col * x_gap, 70 + row * y_gap)
    for index, node in enumerate(file_nodes[1:], start=1):
        positions[node.node_id] = (100, 80 + index * 50)
    return positions


def _short_label(value: str, max_length: int = 22) -> str:
    text = value.strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}..."


def _node_label(nodes: list[WikiGraphNode], node_id: str) -> str:
    for node in nodes:
        if node.node_id == node_id:
            return node.label
    return node_id


def _node_radius(node: WikiGraphNode) -> float:
    if node.node_type == "file":
        return 12
    if node.node_type == "page":
        return 9
    return 6.5
