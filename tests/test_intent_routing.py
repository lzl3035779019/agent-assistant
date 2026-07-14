from typing import Any

from pmaa.config import settings
from pmaa.llm.client import LLMMessage
from pmaa.workflow.graph import run_workflow


class RoutingLLMClient:
    def __init__(self) -> None:
        self.json_calls = 0
        self.text_messages: list[list[LLMMessage]] = []

    def complete_text(self, messages: list[LLMMessage]) -> str:
        self.text_messages.append(messages)
        return "# Routed answer\n\nThis went through the workflow."

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        self.json_calls += 1
        if self.json_calls == 1:
            return {
                "intent": "package_status_query",
                "task_kind": "search_task",
                "execution_mode": "tool_call",
                "need_tools": True,
                "required_tool": "search",
                "should_plan": False,
                "confidence": 0.91,
                "reason": "The user asks for an external lookup.",
            }
        return {
            "passed": True,
            "issues": [],
            "suggested_fix": "",
            "need_retry": False,
        }


class ConflictingRoutingLLMClient(RoutingLLMClient):
    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        self.json_calls += 1
        if self.json_calls == 1:
            return {
                "intent": "weather_query",
                "task_kind": "realtime_query",
                "execution_mode": "direct_answer",
                "need_tools": True,
                "required_tool": "weather",
                "should_plan": False,
                "confidence": 0.95,
                "reason": "The user asks for real-time weather.",
            }
        return super().complete_json(messages)


class PlanningRoutingLLMClient(RoutingLLMClient):
    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        self.json_calls += 1
        if self.json_calls == 1:
            return {
                "intent": "research_report",
                "task_kind": "research_task",
                "execution_mode": "plan_and_execute",
                "need_tools": True,
                "required_tool": "search",
                "should_plan": True,
                "confidence": 0.9,
                "reason": "The user needs a multi-step report.",
            }
        if self.json_calls == 2:
            return {
                "goal": "research report",
                "steps": [
                    {
                        "step_id": "search-1",
                        "description": "Search relevant information.",
                        "agent": "search",
                        "expected_output": "Sources",
                    },
                    {
                        "step_id": "write-1",
                        "description": "Write the answer.",
                        "agent": "writer",
                        "expected_output": "Answer",
                    },
                ],
                "required_agents": ["search", "writer", "reflection"],
                "expected_output": "Source-aware answer",
                "risk_points": [],
            }
        return {
            "passed": True,
            "issues": [],
            "suggested_fix": "",
            "need_retry": False,
        }


class DirectAnswerLLMClient(RoutingLLMClient):
    def complete_text(self, messages: list[LLMMessage]) -> str:
        self.text_messages.append(messages)
        return "这是一个直接回答。"

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        self.json_calls += 1
        return {
            "intent": "simple_direct_request",
            "task_kind": "direct_response",
            "execution_mode": "direct_answer",
            "need_tools": False,
            "required_tool": "none",
            "should_plan": False,
            "confidence": 0.93,
            "reason": "The user asks for a simple response without external tools.",
        }


def test_model_identity_question_uses_direct_answer_route():
    result = run_workflow("你好，你是啥模型")

    assert result.final_result is not None
    assert settings.llm_model in result.final_result.answer
    assert result.sources == []
    assert result.plan is None
    assert [event.agent for event in result.events] == [
        "supervisor",
        "supervisor",
    ]
    assert result.events[0].output["intent"] == "model_identity"
    assert result.events[0].output["execution_mode"] == "direct_answer"
    assert result.events[0].output["required_tool"] == "none"
    assert result.events[0].output["should_plan"] is False


def test_short_greeting_uses_direct_answer_route_without_tools():
    result = run_workflow("hi")

    assert result.final_result is not None
    assert result.sources == []
    assert result.plan is None
    assert result.events[0].output["intent"] == "casual_chat"
    assert result.events[0].output["task_kind"] == "casual_chat"
    assert result.events[0].output["execution_mode"] == "direct_answer"


def test_simple_direct_request_with_llm_generates_answer_without_tools():
    client = DirectAnswerLLMClient()

    result = run_workflow("tell me something fun", llm_client=client)

    assert result.final_result is not None
    assert result.final_result.answer == "这是一个直接回答。"
    assert result.sources == []
    assert result.plan is None
    assert result.events[0].output["intent"] == "simple_direct_request"
    assert result.events[0].output["execution_mode"] == "direct_answer"
    assert result.events[1].event_type == "direct_answer"
    assert client.text_messages


def test_ambiguous_question_asks_for_clarification_without_tools():
    result = run_workflow("this one")

    assert result.final_result is not None
    assert result.sources == []
    assert result.plan is None
    assert result.events[0].output["intent"] == "ambiguous"
    assert result.events[0].output["execution_mode"] == "clarification"
    assert "请补充" in result.final_result.answer


def test_tool_call_route_skips_planner_and_calls_tool_directly():
    client = RoutingLLMClient()

    result = run_workflow("check the latest package status", llm_client=client)

    assert result.final_result is not None
    assert result.plan is not None
    assert result.events[0].output["intent"] == "package_status_query"
    assert result.events[0].output["task_kind"] == "search_task"
    assert result.events[0].output["execution_mode"] == "tool_call"
    assert result.events[0].output["required_tool"] == "search"
    assert result.events[0].output["should_plan"] is False
    assert [event.agent for event in result.events] == [
        "supervisor",
        "tool",
        "writer",
        "reflection",
        "supervisor",
    ]


def test_tool_required_llm_route_is_normalized_to_tool_call():
    client = ConflictingRoutingLLMClient()

    result = run_workflow("今天江西南昌青山湖区天气怎么样", llm_client=client)

    assert result.final_result is not None
    assert result.plan is not None
    assert result.events[0].output["intent"] == "weather_query"
    assert result.events[0].output["task_kind"] == "realtime_query"
    assert result.events[0].output["execution_mode"] == "tool_call"
    assert result.events[0].output["required_tool"] == "search"
    assert result.events[0].output["should_plan"] is False
    assert result.events[0].output["need_tools"] is True


def test_plan_and_execute_route_uses_planner():
    client = PlanningRoutingLLMClient()

    result = run_workflow("make a detailed research report", llm_client=client)

    assert result.final_result is not None
    assert result.plan is not None
    assert result.events[0].output["execution_mode"] == "plan_and_execute"
    assert result.events[0].output["should_plan"] is True
    assert [event.agent for event in result.events] == [
        "supervisor",
        "planner",
        "search",
        "tool",
        "writer",
        "reflection",
        "supervisor",
    ]


def test_weather_query_without_llm_does_not_use_hard_rule():
    result = run_workflow("今天江西南昌青山湖区天气怎么样")

    assert result.final_result is not None
    assert result.plan is None
    assert result.events[0].output["intent"] == "ambiguous"
    assert result.events[0].output["execution_mode"] == "clarification"
