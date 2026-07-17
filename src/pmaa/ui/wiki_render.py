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
DEFAULT_GRAPH_VIEWPORT_HEIGHT = 920


def build_wiki_graph_html(
    graph: WikiGraph,
    width: int | None = None,
    height: int | None = None,
    highlighted_node_ids: set[str] | None = None,
) -> str:
    if not graph.nodes:
        return (
            _graph_styles()
            + '<div class="wiki-empty-graph">暂无图谱数据</div>'
        )

    canvas_width, canvas_height = _canvas_size(len(graph.nodes), width, height)
    positions = _layout_positions(graph.nodes, canvas_width, canvas_height)
    highlighted = {
        node.node_id for node in graph.nodes if node.highlighted
    } | (highlighted_node_ids or set())
    edge_lines: list[str] = []
    edge_details: list[str] = []
    node_details: list[str] = []

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
        edge_detail_id = f"wiki-edge-{index}"
        edge_class = (
            f'wiki-edge-link{" wiki-edge-import" if is_highlighted_edge else ""}'
            f'{" is-selected" if index == 0 else ""}'
        )
        edge_lines.append(
            f'<a href="#{edge_detail_id}" data-detail-target="{edge_detail_id}" class="{edge_class}">'
            f"<title>{edge_title}</title>"
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{edge_stroke}" stroke-width="1" />'
            "</a>"
        )
        detail_class = "wiki-edge-detail is-active" if index == 0 else "wiki-edge-detail"
        edge_details.append(
            f'<div id="{edge_detail_id}" class="{detail_class}">'
            f'<div class="wiki-edge-detail-title">关系 #{index + 1} · {escape(edge.edge_type)}</div>'
            f"<div><b>源节点</b>：{escape(source_label)}</div>"
            f"<div><b>目标节点</b>：{escape(target_label)}</div>"
            f"<div><b>源 ID</b>：<code>{escape(edge.source)}</code></div>"
            f"<div><b>目标 ID</b>：<code>{escape(edge.target)}</code></div>"
            "</div>"
        )

    node_items = []
    for index, node in enumerate(graph.nodes):
        x, y = positions[node.node_id]
        is_highlighted = node.node_id in highlighted
        # A source is the provenance root, never a newly synthesized concept.
        # Keep it slate so red nodes remain legible as this modelling run's pages.
        color = (
            NODE_COLORS.get(node.node_type, "#475569")
            if node.node_type == "source"
            else (
                "#ef4444"
                if is_highlighted
                else NODE_COLORS.get(node.node_type, "#475569")
            )
        )
        short_label = escape(_short_label(node.label))
        full_label = escape(node.label)
        title = escape(f"{node.label} · {node.node_type}")
        radius = _node_radius(node)
        node_detail_id = f"wiki-node-{index}"
        node_items.append(
            f'<g class="wiki-node wiki-node-{escape(node.node_type)}{" wiki-node-highlighted" if is_highlighted else ""}" data-detail-target="{node_detail_id}" tabindex="0" role="button">'
            f"<title>{title}</title>"
            f'<circle class="wiki-node-core" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{color}" stroke="#fffdf8" stroke-width="1.5" />'
            f'<text class="wiki-node-label" x="{x + 13:.1f}" y="{y + 4:.1f}" data-short-label="{short_label}" data-full-label="{full_label}">{short_label}</text>'
            + (
                f'<text class="wiki-node-import-label" x="{x + 13:.1f}" y="{y - 8:.1f}" fill="#dc2626" font-size="10" font-weight="800">本次</text>'
                if is_highlighted and node.node_type != "source"
                else ""
            )
            + "</g>"
        )
        node_details.append(
            f'<div id="{node_detail_id}" class="wiki-node-detail">'
            f'<div class="wiki-edge-detail-title">节点 · {escape(node.node_type)}</div>'
            f"<div><b>名称</b>：{full_label}</div>"
            f"<div><b>ID</b>：<code>{escape(node.node_id)}</code></div>"
            + (
                "<div><b>状态</b>：本次导入相关</div>"
                if is_highlighted
                else ""
            )
            + "</div>"
        )

    default_detail = (
        edge_details[0]
        if edge_details
        else '<div class="wiki-edge-detail is-default">暂无关系</div>'
    )
    viewport_height = DEFAULT_GRAPH_VIEWPORT_HEIGHT
    return (
        _graph_styles()
        + '<div class="wiki-graph-card">'
        + '<div class="wiki-graph-topline">'
        + '<div class="wiki-graph-hint">点击连线查看关系；滚轮缩放，左键拖动画布，放大后显示完整节点名称。</div>'
        + '<div class="wiki-graph-toolbar">'
        + '<button type="button" data-action="zoom-out" aria-label="缩小">-</button>'
        + '<button type="button" data-action="reset" aria-label="重置视图">1:1</button>'
        + '<button type="button" data-action="zoom-in" aria-label="放大">+</button>'
        + '<span class="wiki-graph-zoom">100%</span>'
        + "</div>"
        + "</div>"
        + f'<div class="wiki-graph-viewport" data-wiki-graph data-wiki-graph-height="{viewport_height}" style="height: {viewport_height}px;">'
        + '<div class="wiki-graph-stage">'
        + f'<svg width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}" role="img" aria-label="LLM Wiki graph">'
        + "".join(edge_lines)
        + "".join(node_items)
        + "</svg>"
        + "</div>"
        + "</div>"
        + '<div class="wiki-edge-details">'
        + default_detail
        + "".join(edge_details[1:])
        + "".join(node_details)
        + "</div>"
        + "</div>"
        + _graph_script()
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


def _short_label(value: str, max_length: int = 28) -> str:
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


def _graph_styles() -> str:
    return """
<style>
html, body {
    margin: 0;
    background: #fffefa;
    color: #26231d;
    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.wiki-empty-graph {
    border: 1px dashed #d8d0c3;
    border-radius: 8px;
    background: #fffefa;
    color: #8f8578;
    padding: 28px;
    text-align: center;
}
.wiki-graph-card {
    border: 1px solid #e4dccd;
    border-radius: 8px;
    background: #fffefa;
    padding: 12px;
    overflow: hidden;
    box-sizing: border-box;
}
.wiki-graph-topline {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 8px;
}
.wiki-graph-hint {
    width: fit-content;
    border-radius: 999px;
    background: #eff8f4;
    color: #0f7a70;
    padding: 5px 10px;
    font-size: 12px;
    font-weight: 850;
}
.wiki-graph-toolbar {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    flex: 0 0 auto;
}
.wiki-graph-toolbar button {
    min-width: 34px;
    height: 30px;
    border: 1px solid #d8c9ac;
    border-radius: 6px;
    background: #fffaf0;
    color: #4a3e27;
    cursor: pointer;
    font-weight: 850;
}
.wiki-graph-toolbar button:hover {
    border-color: #b9963c;
    color: #8a6716;
}
.wiki-graph-zoom {
    min-width: 46px;
    color: #6f675b;
    font-size: 12px;
    font-weight: 800;
    text-align: right;
}
.wiki-graph-viewport {
    position: relative;
    min-height: 760px;
    border: 1px solid #efe5d4;
    border-radius: 8px;
    overflow: hidden;
    background:
        radial-gradient(circle at 30% 35%, rgba(15, 139, 127, .06), transparent 26%),
        #fffefa;
    cursor: grab;
    touch-action: none;
    user-select: none;
}
.wiki-graph-viewport.is-dragging {
    cursor: grabbing;
}
.wiki-graph-stage {
    position: absolute;
    left: 0;
    top: 0;
    transform-origin: 0 0;
    will-change: transform;
}
.wiki-graph-stage svg {
    display: block;
    overflow: visible;
}
.wiki-edge-link line {
    stroke: rgba(91, 82, 68, .18);
    stroke-width: 1.1;
    cursor: pointer;
    transition: stroke .12s ease, stroke-width .12s ease;
}
.wiki-edge-link:hover line,
.wiki-edge-link:focus line {
    stroke: #0f8b7f;
    stroke-width: 2.4;
}
.wiki-edge-link.is-selected line {
    stroke: #0f8b7f !important;
    stroke-width: 3px !important;
    opacity: 1 !important;
}
.wiki-edge-link.wiki-edge-import line {
    stroke: #ef4444 !important;
    stroke-width: 1.1px !important;
    opacity: .85 !important;
}
.wiki-edge-link.wiki-edge-import.is-selected line {
    stroke: #dc2626 !important;
    stroke-width: 3px !important;
}
.wiki-node {
    cursor: pointer;
}
.wiki-node:focus .wiki-node-core,
.wiki-node:hover .wiki-node-core {
    stroke: #0f8b7f !important;
    stroke-width: 2.4px !important;
}
.wiki-node.is-selected .wiki-node-core {
    stroke: #0f8b7f !important;
    stroke-width: 3px !important;
    filter: drop-shadow(0 2px 6px rgba(15, 139, 127, .35));
}
.wiki-node.is-selected text {
    fill: #0f7a70 !important;
    font-weight: 950 !important;
}
.wiki-node text {
    font-size: 11px;
    font-weight: 750;
    fill: #423b31;
    paint-order: stroke;
    stroke: #fffefa;
    stroke-width: 3px;
    stroke-linejoin: round;
}
.wiki-node circle {
    stroke: #fffefa;
    stroke-width: 1.8;
}
.wiki-node-highlighted .wiki-node-core {
    fill: #ef4444 !important;
    stroke: #7f1d1d !important;
    stroke-width: 2.2px !important;
}
.wiki-node-highlighted text {
    fill: #b91c1c !important;
    font-weight: 900 !important;
}
.wiki-edge-details {
    max-width: 760px;
    margin-top: 10px;
}
.wiki-edge-detail,
.wiki-node-detail {
    display: none;
    border: 1px solid #d6e9df;
    border-radius: 8px;
    background: #fbfff9;
    color: #2b2924;
    padding: 10px 12px;
    line-height: 1.7;
    font-size: 13px;
}
.wiki-edge-detail.is-active,
.wiki-node-detail.is-active {
    display: block;
    box-shadow: 0 10px 28px rgba(15, 139, 127, .12);
}
.wiki-edge-detail-title {
    color: #0f7a70;
    font-weight: 900;
    margin-bottom: 4px;
}
@media (max-width: 720px) {
    .wiki-graph-topline {
        align-items: flex-start;
        flex-direction: column;
    }
    .wiki-graph-hint {
        border-radius: 8px;
        line-height: 1.5;
    }
}
</style>
"""


def _graph_script() -> str:
    return """
<script>
(function () {
    function setupGraph(viewport) {
        if (viewport.dataset.panZoomReady === '1') {
            return;
        }
        viewport.dataset.panZoomReady = '1';

        const card = viewport.closest('.wiki-graph-card');
        const stage = viewport.querySelector('.wiki-graph-stage');
        const zoomLabel = card.querySelector('.wiki-graph-zoom');
        const labels = Array.from(viewport.querySelectorAll('.wiki-node-label'));
        const detailItems = Array.from(card.querySelectorAll('.wiki-edge-detail, .wiki-node-detail'));
        const detailTriggers = Array.from(card.querySelectorAll('[data-detail-target]'));
        let scale = 1;
        let offsetX = 0;
        let offsetY = 0;
        let dragStart = null;
        const minScale = 0.35;
        const maxScale = 4;

        function clampScale(value) {
            return Math.min(maxScale, Math.max(minScale, value));
        }

        function updateLabels() {
            const useFullLabel = scale >= 1.45;
            labels.forEach((label) => {
                const nextLabel = useFullLabel ? label.dataset.fullLabel : label.dataset.shortLabel;
                if (label.textContent !== nextLabel) {
                    label.textContent = nextLabel;
                }
            });
        }

        function showDetail(targetId) {
            detailItems.forEach((item) => {
                item.classList.toggle('is-active', item.id === targetId);
            });
            detailTriggers.forEach((trigger) => {
                trigger.classList.toggle('is-selected', trigger.dataset.detailTarget === targetId);
            });
        }

        detailTriggers.forEach((trigger) => {
            trigger.addEventListener('click', (event) => {
                event.preventDefault();
                const targetId = trigger.dataset.detailTarget;
                showDetail(targetId);
            });
            trigger.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter' && event.key !== ' ') {
                    return;
                }
                event.preventDefault();
                const targetId = trigger.dataset.detailTarget;
                showDetail(targetId);
            });
        });

        function applyTransform() {
            stage.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
            zoomLabel.textContent = `${Math.round(scale * 100)}%`;
            updateLabels();
        }

        function zoomAt(nextScale, clientX, clientY) {
            const previousScale = scale;
            scale = clampScale(nextScale);
            const rect = viewport.getBoundingClientRect();
            const originX = clientX - rect.left;
            const originY = clientY - rect.top;
            const graphX = (originX - offsetX) / previousScale;
            const graphY = (originY - offsetY) / previousScale;
            offsetX = originX - graphX * scale;
            offsetY = originY - graphY * scale;
            applyTransform();
        }

        card.querySelector('[data-action="zoom-in"]').addEventListener('click', () => {
            const rect = viewport.getBoundingClientRect();
            zoomAt(scale * 1.2, rect.left + rect.width / 2, rect.top + rect.height / 2);
        });
        card.querySelector('[data-action="zoom-out"]').addEventListener('click', () => {
            const rect = viewport.getBoundingClientRect();
            zoomAt(scale / 1.2, rect.left + rect.width / 2, rect.top + rect.height / 2);
        });
        card.querySelector('[data-action="reset"]').addEventListener('click', () => {
            scale = 1;
            offsetX = 0;
            offsetY = 0;
            applyTransform();
        });

        viewport.addEventListener('wheel', (event) => {
            event.preventDefault();
            const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
            zoomAt(scale * factor, event.clientX, event.clientY);
        }, { passive: false });

        viewport.addEventListener('pointerdown', (event) => {
            if (event.button !== 0) {
                return;
            }
            if (event.target.closest('[data-detail-target]')) {
                return;
            }
            dragStart = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                offsetX,
                offsetY,
            };
            viewport.classList.add('is-dragging');
            viewport.setPointerCapture(event.pointerId);
        });

        viewport.addEventListener('pointermove', (event) => {
            if (!dragStart) {
                return;
            }
            offsetX = dragStart.offsetX + event.clientX - dragStart.startX;
            offsetY = dragStart.offsetY + event.clientY - dragStart.startY;
            applyTransform();
        });

        function endDrag(event) {
            if (!dragStart) {
                return;
            }
            viewport.classList.remove('is-dragging');
            if (viewport.hasPointerCapture(dragStart.pointerId)) {
                viewport.releasePointerCapture(dragStart.pointerId);
            }
            dragStart = null;
        }

        viewport.addEventListener('pointerup', endDrag);
        viewport.addEventListener('pointercancel', endDrag);
        applyTransform();
    }

    document.querySelectorAll('[data-wiki-graph]').forEach(setupGraph);
})();
</script>
"""
