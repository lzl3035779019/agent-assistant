from typing import Any

from pmaa.llm.client import LLMMessage
from pmaa.skills.registry import LocalSkillRegistry
from pmaa.workflow.graph import run_workflow


class CapturingRoutingLLMClient:
    def __init__(self) -> None:
        self.json_messages: list[list[LLMMessage]] = []

    def complete_text(self, messages: list[LLMMessage]) -> str:
        return "Direct answer."

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        self.json_messages.append(messages)
        return {
            "intent": "research_report",
            "task_kind": "research_task",
            "execution_mode": "tool_call",
            "need_tools": True,
            "required_tool": "search",
            "should_plan": False,
            "confidence": 0.92,
            "reason": "Need external research.",
        }


def test_workflow_loads_skill_catalog_before_supervisor_without_trigger_matching(tmp_path):
    skill_dir = tmp_path / "skills" / "research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: search_research
description: Search external sources and produce research notes.
triggers:
  - never-match-this-trigger
enabled: true
---

# Rules

Keep source links in the final answer.
""",
        encoding="utf-8",
    )
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    client = CapturingRoutingLLMClient()

    result = run_workflow(
        "Help me research LangGraph",
        llm_client=client,
        skill_registry=registry,
        enable_skills=True,
    )

    assert result.events[0].agent == "skills"
    assert result.events[0].output["catalog_count"] == 1
    assert result.events[0].output["skill_ids"] == ["search_research"]
    assert "<!-- Skill Catalog -->" in result.conversation_context
    assert "<name>search_research</name>" in result.conversation_context
    assert "<description>Search external sources and produce research notes.</description>" in result.conversation_context
    assert "<tool_name>skill:search_research</tool_name>" in result.conversation_context
    assert "never-match-this-trigger" not in result.conversation_context
    assert "Keep source links in the final answer." not in result.conversation_context
    prompt_text = "\n".join(message.content for message in client.json_messages[0])
    assert "<!-- Skill Catalog -->" in prompt_text
    assert "<name>search_research</name>" in prompt_text


def test_disabled_skill_is_not_injected_into_workflow(tmp_path):
    skill_dir = tmp_path / "skills" / "research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: search_research
description: Search external sources and produce research notes.
triggers:
  - research
enabled: true
---

# Rules

Keep source links in the final answer.
""",
        encoding="utf-8",
    )
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    registry.set_enabled("search_research", False)
    client = CapturingRoutingLLMClient()

    result = run_workflow(
        "Help me research LangGraph",
        llm_client=client,
        skill_registry=registry,
        enable_skills=True,
    )

    assert result.events[0].agent == "skills"
    assert result.events[0].output["catalog_count"] == 0
    assert "<!-- Skill Catalog -->" not in result.conversation_context
