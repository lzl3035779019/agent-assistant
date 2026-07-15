from typing import Any

from pmaa.agents.memory import MemoryAgent
from pmaa.llm.client import LLMMessage
from pmaa.storage.memory_store import SQLiteMemoryStore
from pmaa.workflow.graph import _extract_url_to_open, build_workflow_graph, run_workflow


class RecordingWorkflowLLMClient:
    def __init__(self) -> None:
        self.text_messages: list[list[LLMMessage]] = []
        self.json_messages: list[list[LLMMessage]] = []

    def complete_text(self, messages: list[LLMMessage]) -> str:
        self.text_messages.append(messages)
        return "# 回答\n\n基于资料来源 [S1]。"

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        self.json_messages.append(messages)
        if len(self.json_messages) == 1:
            return {
                "goal": "回答追问",
                "steps": [
                    {
                        "step_id": "search-1",
                        "description": "搜索追问相关资料",
                        "agent": "search",
                        "expected_output": "资料来源",
                    },
                    {
                        "step_id": "write-1",
                        "description": "结合上下文回答",
                        "agent": "writer",
                        "expected_output": "Markdown 回答",
                    },
                ],
                "required_agents": ["search", "writer", "reflection"],
                "expected_output": "带上下文的回答",
                "risk_points": [],
            }
        return {
            "passed": True,
            "issues": [],
            "suggested_fix": "",
            "need_retry": False,
        }


class StubMemoryConsolidationLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete_text(self, messages: list[LLMMessage]) -> str:
        return ""

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        self.calls += 1
        return {
            "candidates": [
                {
                    "type": "preference",
                    "content": "用户喜欢看新闻，尤其关注 AI 新闻。",
                    "source": "user",
                    "confidence": 0.92,
                    "should_save": True,
                    "reason": "稳定兴趣偏好。",
                }
            ]
        }


def test_workflow_graph_is_langgraph_state_graph():
    graph = build_workflow_graph()

    drawable = graph.get_graph()

    assert {
        "supervisor",
        "planner",
        "search",
        "tool",
        "writer",
        "reflection",
        "finalize",
    }.issubset(set(drawable.nodes))


def test_workflow_returns_answer_sources_and_events():
    result = run_workflow("帮我研究 LangGraph 的核心概念，并生成学习路线")

    assert result.final_result is not None
    assert "LangGraph" in result.final_result.answer
    assert result.final_result.sources
    assert result.final_result.reflection.passed is True
    assert [event.agent for event in result.events] == [
        "supervisor",
        "planner",
        "search",
        "tool",
        "writer",
        "reflection",
        "supervisor",
    ]


def test_extract_url_to_open_prefers_product_official_site_over_baidu_homepage():
    query = "\u6253\u5f00\u767e\u5ea6\u6587\u5fc3\u4e00\u8a00\u5927\u6a21\u578b\u7684\u5b98\u7f51"

    assert _extract_url_to_open(query) == "https://yiyan.baidu.com"


def test_workflow_consolidates_memory_after_final_answer(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    llm = StubMemoryConsolidationLLM()
    memory_agent = MemoryAgent(store, llm_client=llm)

    result = run_workflow(
        "我喜欢看新闻，搜索今天最火的 AI 新闻",
        memory_agent=memory_agent,
        enable_memory=True,
    )

    saved = store.list_all()
    memory_event = next(
        event
        for event in result.events
        if event.agent == "memory" and event.event_type == "updated"
    )

    assert llm.calls == 1
    assert len(saved) == 1
    assert "喜欢看新闻" in saved[0].content
    assert memory_event.output["saved_count"] == 1


def test_workflow_passes_conversation_context_to_llm_agents():
    client = RecordingWorkflowLLMClient()

    run_workflow(
        "那它适合做什么？",
        llm_client=client,
        conversation_context="上一轮用户问：LangGraph 是什么？\n上一轮回答：LangGraph 用于构建有状态 Agent。",
    )

    planner_prompt = "\n".join(message.content for message in client.json_messages[0])
    writer_prompt = "\n".join(message.content for message in client.text_messages[0])

    assert "LangGraph 是什么" in planner_prompt
    assert "LangGraph 用于构建有状态 Agent" in writer_prompt
