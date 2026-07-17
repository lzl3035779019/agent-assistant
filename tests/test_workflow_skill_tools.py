from pathlib import Path
from typing import Any

from pmaa.llm.client import LLMMessage
from pmaa.skills.actions import create_default_action_registry
from pmaa.skills.registry import LocalSkillRegistry
from pmaa.skills.tool_binding import SkillToolBindingService
from pmaa.workflow.graph import run_workflow


class SkillToolRoutingLLMClient:
    def complete_text(self, messages: list[LLMMessage]) -> str:
        return "Skill tool executed."

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
            "intent": "browser_task",
            "task_kind": "tool_task",
            "execution_mode": "tool_call",
            "need_tools": True,
            "required_tool": "skill:agent_browser",
            "should_plan": False,
            "confidence": 0.93,
            "reason": "Use the enabled browser skill.",
        }


def test_workflow_can_route_to_registered_skill_tool(tmp_path):
    skill_dir = tmp_path / "skills" / "agent_browser"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: agent-browser
description: Browser automation CLI for AI agents.
triggers:
  - browser
enabled: true
---

# agent-browser

Run `agent-browser skills get core`.
""",
        encoding="utf-8",
    )
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    def fake_runner(command: list[str], timeout: int):
        raise AssertionError("Browser tasks should build an action plan, not run health check.")

    result = run_workflow(
        "Open the browser and inspect the page",
        llm_client=SkillToolRoutingLLMClient(),
        skill_registry=registry,
        enable_skills=True,
        skill_tool_binding_service=SkillToolBindingService(
            command_exists=lambda command: True,
            runner=fake_runner,
            action_registry=create_default_action_registry(),
        ),
    )

    supervisor_event = next(event for event in result.events if event.agent == "supervisor")
    tool_event = next(event for event in result.events if event.agent == "tool")

    assert supervisor_event.output["required_tool"] == "skill:agent_browser"
    assert supervisor_event.output["selected_skill_id"] == "agent_browser"
    assert "<!-- Skill Catalog -->" in result.conversation_context
    assert "<!-- Selected Skill -->" in result.conversation_context
    assert "Run `agent-browser skills get core`." in result.conversation_context
    assert tool_event.output["tool_name"] == "skill:agent_browser"
    assert tool_event.output["tool_result"]["success"] is False
    assert tool_event.output["tool_result"]["action"] == "browser.task"
    assert "browser.open_url" in tool_event.output["tool_result"]["supported_actions"]
    assert "browser.task" in tool_event.output["tool_result"]["supported_actions"]
    assert tool_event.output["tool_result"]["permission_level"] == "network"
    assert tool_event.output["tool_result"]["status"] == "confirmation_required"
    assert result.pending_confirmation["action"] == "browser.task"
    assert result.pending_confirmation["plan"]["goal"] == "Open the browser and inspect the page"
    assert result.final_result is None


def test_workflow_stops_when_skill_action_requires_confirmation(tmp_path):
    skill_dir = tmp_path / "skills" / "agent_browser"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: agent-browser
description: Browser automation CLI for AI agents.
enabled: true
---

# agent-browser

Run `agent-browser skills get core`.
""",
        encoding="utf-8",
    )
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    def fake_runner(command: list[str], timeout: int):
        return 0, "agent-browser 1.0.0", ""

    class OpenUrlBindingService(SkillToolBindingService):
        def _build_version_tool(self, binding):
            tool = super()._build_version_tool(binding)

            def _open_url(*args, **kwargs):
                return tool(
                    {
                        "action": "browser.open_url",
                        "args": {"url": "https://example.com"},
                    }
                )

            return _open_url

    result = run_workflow(
        "Open https://example.com",
        llm_client=SkillToolRoutingLLMClient(),
        skill_registry=registry,
        enable_skills=True,
        skill_tool_binding_service=OpenUrlBindingService(
            command_exists=lambda command: True,
            runner=fake_runner,
            action_registry=create_default_action_registry(),
        ),
    )

    confirmation = result.pending_confirmation
    tool_event = next(event for event in result.events if event.agent == "tool")

    assert confirmation["status"] == "confirmation_required"
    assert confirmation["action"] == "browser.open_url"
    assert confirmation["permission_level"] == "network"
    assert confirmation["plan"]["url"] == "https://example.com"
    assert result.final_result is None
    assert result.draft_answer == ""
    assert tool_event.output["tool_result"]["status"] == "confirmation_required"
    assert result.events[-1].agent == "supervisor"
    assert result.events[-1].event_type == "await_confirmation"


def test_workflow_builds_open_url_confirmation_from_simple_open_request(tmp_path):
    skill_dir = tmp_path / "skills" / "agent_browser"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: agent-browser
description: Browser automation CLI for AI agents.
enabled: true
---

# agent-browser

Run `agent-browser skills get core`.
""",
        encoding="utf-8",
    )
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    result = run_workflow(
        "open https://www.baidu.com",
        llm_client=SkillToolRoutingLLMClient(),
        skill_registry=registry,
        enable_skills=True,
        skill_tool_binding_service=SkillToolBindingService(
            command_exists=lambda command: True,
            runner=lambda command, timeout: (0, "agent-browser 1.0.0", ""),
            action_registry=create_default_action_registry(),
        ),
    )

    assert result.pending_confirmation["action"] == "browser.open_url"
    assert result.pending_confirmation["plan"]["url"] == "https://www.baidu.com"
    assert result.final_result is None
