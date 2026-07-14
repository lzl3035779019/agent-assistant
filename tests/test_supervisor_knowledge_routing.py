from typing import Any

from pmaa.agents.supervisor import SupervisorAgent
from pmaa.llm.client import LLMMessage


class LowConfidenceRouter:
    """Simulates the faulty LLM decision shown in the UI regression."""

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        return {
            "intent": "ambiguous",
            "task_kind": "unknown",
            "execution_mode": "clarification",
            "need_tools": False,
            "required_tool": "none",
            "should_plan": False,
            "confidence": 0.45,
            "reason": "输入目标不明确。",
        }


def test_explicit_knowledge_base_question_bypasses_low_confidence_llm_route():
    decision = SupervisorAgent(llm_client=LowConfidenceRouter()).classify_intent(
        "根据我的知识库，解释 Naive RAG 存在的不足"
    )

    assert decision.execution_mode == "tool_call"
    assert decision.need_tools is True
    assert decision.required_tool == "knowledge"
    assert decision.task_kind == "knowledge_task"


def test_domain_fact_question_uses_available_knowledge_without_magic_prefix():
    decision = SupervisorAgent(knowledge_available=True).classify_intent(
        "Workflow 和 Agent 有什么区别？"
    )

    assert decision.execution_mode == "tool_call"
    assert decision.required_tool == "knowledge"
    assert "本地证据" in decision.reason


def test_domain_fact_question_does_not_route_to_missing_knowledge_tool():
    decision = SupervisorAgent(knowledge_available=False).classify_intent(
        "Workflow 和 Agent 有什么区别？"
    )

    assert decision.required_tool != "knowledge"


def test_joke_request_is_a_direct_answer_not_a_clarification():
    decision = SupervisorAgent().classify_intent("给我讲一个笑话")

    assert decision.intent == "casual_response"
    assert decision.execution_mode == "direct_answer"
    assert decision.required_tool == "none"


def test_explicit_wiki_slug_reads_the_page_directly():
    decision = SupervisorAgent().classify_intent(
        "请读取 gbrain://page/wiki/concept/1981df94c33652"
    )

    assert decision.execution_mode == "tool_call"
    assert decision.required_tool == "wiki_get_page"
