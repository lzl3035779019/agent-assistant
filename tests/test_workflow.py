from typing import Any

from pmaa.llm.client import LLMMessage
from pmaa.workflow.graph import build_workflow_graph, run_workflow


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
