import sys
from pathlib import Path

from pmaa.tools.gbrain import GBrainGetPageTool, GBrainKnowledgeTool, parse_gbrain_sources
from pmaa.tools.mcp_client import MCPClient, MCPServerConfig


def test_parse_gbrain_sources_accepts_result_envelope():
    sources = parse_gbrain_sources(
        {
            "results": [
                {
                    "title": "LLM Wiki",
                    "uri": "gbrain://wiki/llm",
                    "text": "LLM Wiki knowledge",
                    "relevance": 0.88,
                }
            ]
        }
    )

    assert sources[0].title == "LLM Wiki"
    assert sources[0].url == "gbrain://wiki/llm"
    assert "LLM Wiki knowledge" in sources[0].snippet
    assert "0.88" in sources[0].snippet


def test_parse_gbrain_sources_preserves_chunk_and_document_provenance():
    sources = parse_gbrain_sources(
        {
            "results": [
                {
                    "title": "RAG 检索质量评估指标",
                    "slug": "wiki/concept/rag-metrics",
                    "chunk_text": "召回率不足会让后续生成无法补救。",
                    "chunk_id": 42,
                    "chunk_index": 2,
                    "score": 0.91,
                    "source_document_title": "Agentic RAG 面试题",
                    "source_document_filename": "agentic_rag_review.md",
                    "source_document_path": "C:\\Users\\lzl\\GbrainInbox\\agentic_rag_review.md",
                    "source_slug": "sources/documents/abc",
                    "import_id": "import-1",
                }
            ]
        }
    )

    source = sources[0]
    assert source.page_slug == "wiki/concept/rag-metrics"
    assert source.document_title == "Agentic RAG 面试题"
    assert source.document_filename == "agentic_rag_review.md"
    assert source.chunk_id == 42
    assert source.chunk_index == 2
    assert source.score == 0.91
    assert "召回率不足" in source.snippet


def test_gbrain_knowledge_tool_calls_stdio_mcp_server():
    server_path = Path(__file__).parent / "fake_gbrain_mcp_server.py"
    client = MCPClient(
        MCPServerConfig(
            transport="stdio",
            command=sys.executable,
            args=[str(server_path)],
            cwd=Path.cwd(),
        )
    )
    tool = GBrainKnowledgeTool(client, max_results=2)

    sources = tool("PMAA")

    assert sources[0].title == "PMAA"
    assert sources[0].url == "gbrain://page/concepts/pmaa"
    assert "PMAA" in sources[0].snippet


def test_gbrain_knowledge_tool_uses_complete_markdown_section_not_fixed_next_chunks():
    class SourceAwareClient:
        def call_tool(self, name, arguments):
            if name == "query":
                assert arguments["expand"] is True
                assert arguments["detail"] == "high"
                return {
                    "results": [
                        {
                            "title": "Agent 面试资料",
                            "slug": "sources/documents/agent-notes",
                            "page_slug": "sources/documents/agent-notes",
                            "chunk_index": 5,
                            "chunk_text": "### Agent 的工作模式都有什么？\n"
                            "(1) ToolsCallingAgent\n(2) ReActAgent",
                        }
                    ]
                }
            assert name == "get_page"
            assert arguments == {"slug": "sources/documents/agent-notes"}
            return {
                "compiled_truth": """<details><summary>完整原始文本</summary>
# Agent 面试题

### Agent 的工作模式都有什么？
(1) ToolsCallingAgent
(2) ReActAgent
(3) ReflectionAgent
(4) PlanAndSolveAgent
(5) Multi-Agent
(6) Human-in-the-Loop

### Agent 的设计范式是什么？
这里不应被带入工作模式的证据。
</details>"""
            }

    tool = GBrainKnowledgeTool(SourceAwareClient(), search_tool_name="query")

    sources = tool("Agent 的工作模式都有什么？")

    assert "Human-in-the-Loop" in sources[0].snippet
    assert "这里不应被带入" not in sources[0].snippet
    assert "固定数量的相邻分块" in sources[0].snippet


def test_gbrain_knowledge_tool_falls_back_to_original_query_only_after_empty_expansion():
    class ExpansionEmptyClient:
        def __init__(self):
            self.calls = []

        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            if arguments.get("expand") is True:
                return {"results": []}
            return {
                "results": [
                    {
                        "title": "Workflow 与 Agent",
                        "slug": "wiki/concept/workflow-agent",
                        "chunk_text": "Workflow 是预定义路径，Agent 能动态决定工具和步骤。",
                    }
                ]
            }

    client = ExpansionEmptyClient()
    tool = GBrainKnowledgeTool(client, search_tool_name="query")

    sources = tool("Workflow 和 Agent 有什么区别？")

    assert len(sources) == 1
    assert [arguments["expand"] for _, arguments in client.calls] == [True, False]


def test_gbrain_get_page_tool_calls_stdio_mcp_server():
    server_path = Path(__file__).parent / "fake_gbrain_mcp_server.py"
    client = MCPClient(
        MCPServerConfig(
            transport="stdio",
            command=sys.executable,
            args=[str(server_path)],
            cwd=Path.cwd(),
        )
    )
    tool = GBrainGetPageTool(client)

    sources = tool("wiki/documents/pmaa/index")

    assert sources[0].title == "Wiki Page"
    assert sources[0].url == "gbrain://page/wiki/documents/pmaa/index"
    assert "Full wiki content" in sources[0].snippet
