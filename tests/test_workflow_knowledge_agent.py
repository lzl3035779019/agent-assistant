from typing import Any

from pmaa.llm.client import LLMMessage
from pmaa.schemas.task import Source
from pmaa.workflow.graph import run_workflow


class KnowledgeRoutingLLMClient:
    def complete_text(self, messages: list[LLMMessage]) -> str:
        return "Answer grounded in the local knowledge base."

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        prompt_text = "\n".join(message.content for message in messages)
        if "Evaluate" in prompt_text:
            return {
                "passed": True,
                "issues": [],
                "suggested_fix": "",
                "need_retry": False,
            }
        return {
            "intent": "wiki_search",
            "task_kind": "knowledge_task",
            "execution_mode": "tool_call",
            "need_tools": True,
            "required_tool": "knowledge",
            "should_plan": False,
            "confidence": 0.95,
            "reason": "Use local GBrain knowledge base.",
        }


class WikiGetPageRoutingLLMClient(KnowledgeRoutingLLMClient):
    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        prompt_text = "\n".join(message.content for message in messages)
        if "Evaluate" in prompt_text:
            return {
                "passed": True,
                "issues": [],
                "suggested_fix": "",
                "need_retry": False,
            }
        return {
            "intent": "wiki_get_page",
            "task_kind": "knowledge_task",
            "execution_mode": "tool_call",
            "need_tools": True,
            "required_tool": "wiki_get_page",
            "should_plan": False,
            "confidence": 0.95,
            "reason": "Read a full GBrain wiki page.",
        }


def test_workflow_routes_knowledge_tool_call_through_knowledge_agent(monkeypatch):
    monkeypatch.setattr(
        "pmaa.workflow.graph.create_knowledge_tool",
        lambda: lambda query: [
            Source(
                title="GBrain note",
                url="gbrain://page/1",
                snippet=f"Local wiki hit: {query}",
            )
        ],
    )

    result = run_workflow(
        "Search GBrain knowledge base for PMAA architecture",
        llm_client=KnowledgeRoutingLLMClient(),
    )

    event_agents = [event.agent for event in result.events]
    knowledge_event = next(event for event in result.events if event.agent == "knowledge")
    tool_event = next(event for event in result.events if event.agent == "tool")

    assert "knowledge" in event_agents
    assert "search" not in event_agents
    assert knowledge_event.output == {
        "tool_name": "knowledge",
        "query": "Search GBrain knowledge base for PMAA architecture",
    }
    assert tool_event.output["tool_name"] == "knowledge"
    assert tool_event.output["source_count"] == 1
    assert result.sources[0].url == "gbrain://page/1"
    assert result.final_result is not None


def test_workflow_routes_wiki_get_page_through_knowledge_agent(monkeypatch):
    monkeypatch.setattr("pmaa.workflow.graph.create_knowledge_tool", lambda: None)
    monkeypatch.setattr(
        "pmaa.workflow.graph.create_wiki_get_page_tool",
        lambda: lambda slug: [
            Source(
                title="GBrain full page",
                url=f"gbrain://page/{slug}",
                snippet=f"Full page: {slug}",
            )
        ],
    )

    result = run_workflow(
        "Read wiki/documents/pmaa/index",
        llm_client=WikiGetPageRoutingLLMClient(),
    )

    knowledge_event = next(event for event in result.events if event.agent == "knowledge")
    tool_event = next(event for event in result.events if event.agent == "tool")

    assert knowledge_event.output == {
        "tool_name": "wiki_get_page",
        "query": "wiki/documents/pmaa/index",
    }
    assert tool_event.output["tool_name"] == "wiki_get_page"
    assert result.sources[0].url == "gbrain://page/wiki/documents/pmaa/index"
    assert result.final_result is not None
