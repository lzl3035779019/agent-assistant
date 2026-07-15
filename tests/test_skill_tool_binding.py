from pathlib import Path

from pmaa.schemas.skill import SkillRecord
from pmaa.skills.actions import create_default_action_registry
from pmaa.skills.tool_binding import (
    SkillActionLog,
    SkillToolBindingService,
    _run_version_command,
)
from pmaa.tools.registry import ToolRegistry


def test_skill_tool_binding_creates_safe_tool_name_for_runtime_command():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
        enabled=True,
    )

    bindings = SkillToolBindingService(command_exists=lambda command: True).bindings_for(skill)

    assert len(bindings) == 1
    assert bindings[0].tool_name == "skill:agent_browser"
    assert bindings[0].command_name == "agent-browser"
    assert bindings[0].available is True


def test_skill_tool_binding_registers_version_check_tool():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
        enabled=True,
    )
    registry = ToolRegistry()

    def fake_runner(command: list[str], timeout: int):
        assert command == ["agent-browser", "--version"]
        return 0, "agent-browser 1.0.0", ""

    SkillToolBindingService(
        command_exists=lambda command: True,
        runner=fake_runner,
    ).register_bindings(registry, [skill])

    result = registry.call("skill:agent_browser")

    assert result["tool_name"] == "skill:agent_browser"
    assert result["command"] == ["agent-browser", "--version"]
    assert result["returncode"] == 0
    assert result["stdout"] == "agent-browser 1.0.0"


def test_skill_tool_binding_returns_trusted_action_metadata():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
        enabled=True,
    )
    audit_log = SkillActionLog()
    registry = ToolRegistry()

    SkillToolBindingService(
        command_exists=lambda command: True,
        runner=lambda command, timeout: (0, "agent-browser 1.0.0", ""),
        audit_log=audit_log,
    ).register_bindings(registry, [skill])

    result = registry.call("skill:agent_browser", {"action": "health_check"})

    assert result["success"] is True
    assert result["action"] == "health_check"
    assert result["supported_actions"] == ["health_check"]
    assert result["permission_level"] == "safe"
    assert result["requires_confirmation"] is False
    assert result["rollback"]["status"] == "not_required"
    assert len(audit_log.entries) == 1
    assert audit_log.entries[0]["tool_name"] == "skill:agent_browser"
    assert audit_log.entries[0]["action"] == "health_check"
    assert audit_log.entries[0]["allowed"] is True


def test_skill_tool_binding_applies_same_protocol_to_multiple_skills():
    browser_skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
        enabled=True,
    )
    document_skill = SkillRecord(
        skill_id="docx_helper",
        name="docx-helper",
        source_path=Path("skills/docx_helper/SKILL.md"),
        body="Run `docx-helper inspect template.docx`.",
        enabled=True,
    )
    registry = ToolRegistry()
    commands: list[list[str]] = []

    def fake_runner(command: list[str], timeout: int):
        commands.append(command)
        return 0, f"{command[0]} 1.0.0", ""

    SkillToolBindingService(
        command_exists=lambda command: True,
        runner=fake_runner,
    ).register_bindings(registry, [browser_skill, document_skill])

    browser_result = registry.call("skill:agent_browser", {"action": "health_check"})
    document_result = registry.call("skill:docx_helper", {"action": "health_check"})

    assert browser_result["skill_id"] == "agent_browser"
    assert document_result["skill_id"] == "docx_helper"
    assert browser_result["permission_level"] == document_result["permission_level"] == "safe"
    assert browser_result["supported_actions"] == document_result["supported_actions"] == ["health_check"]
    assert commands == [["agent-browser", "--version"], ["docx-helper", "--version"]]


def test_skill_tool_binding_rejects_unsupported_actions_before_command_runs():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
        enabled=True,
    )
    audit_log = SkillActionLog()
    registry = ToolRegistry()

    def runner(command: list[str], timeout: int):
        raise AssertionError("Unsupported actions must not execute commands.")

    SkillToolBindingService(
        command_exists=lambda command: True,
        runner=runner,
        audit_log=audit_log,
    ).register_bindings(registry, [skill])

    result = registry.call("skill:agent_browser", {"action": "browser.open", "args": {"url": "https://example.com"}})

    assert result["success"] is False
    assert result["action"] == "browser.open"
    assert result["error"] == "Unsupported skill action."
    assert result["rollback"]["status"] == "not_started"
    assert len(audit_log.entries) == 1
    assert audit_log.entries[0]["allowed"] is False


def test_skill_tool_binding_dispatches_registered_adapter_as_dry_run():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        description="Browser automation CLI for AI agents.",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
        enabled=True,
    )
    audit_log = SkillActionLog()
    registry = ToolRegistry()

    SkillToolBindingService(
        command_exists=lambda command: True,
        runner=lambda command, timeout: (0, "agent-browser 1.0.0", ""),
        audit_log=audit_log,
        action_registry=create_default_action_registry(),
    ).register_bindings(registry, [skill])

    result = registry.call(
        "skill:agent_browser",
        {"action": "browser.open_url", "args": {"url": "https://example.com"}},
    )

    assert result["success"] is False
    assert result["status"] == "confirmation_required"
    assert result["supported_actions"] == ["health_check", "browser.open_url", "browser.task"]
    assert result["permission_level"] == "network"
    assert result["requires_confirmation"] is True
    assert result["dry_run"] is True
    assert result["plan"]["url"] == "https://example.com"
    assert audit_log.entries[-1]["action"] == "browser.open_url"
    assert audit_log.entries[-1]["allowed"] is True


def test_skill_tool_binding_dispatches_browser_task_adapter_as_dry_run():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        description="Browser automation CLI for AI agents.",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
        enabled=True,
    )
    audit_log = SkillActionLog()
    registry = ToolRegistry()

    SkillToolBindingService(
        command_exists=lambda command: True,
        runner=lambda command, timeout: (0, "agent-browser 1.0.0", ""),
        audit_log=audit_log,
        action_registry=create_default_action_registry(),
    ).register_bindings(registry, [skill])

    result = registry.call(
        "skill:agent_browser",
        {
            "action": "browser.task",
            "args": {
                "goal": "打开示例网站并截图",
                "start_url": "https://example.com",
                "steps": ["打开网页", "截图"],
            },
        },
    )

    assert result["success"] is False
    assert result["status"] == "confirmation_required"
    assert result["supported_actions"] == ["health_check", "browser.open_url", "browser.task"]
    assert result["permission_level"] == "network"
    assert result["requires_confirmation"] is True
    assert result["dry_run"] is True
    assert result["plan"]["goal"] == "打开示例网站并截图"
    assert result["plan"]["start_url"] == "https://example.com"
    assert "agent-browser screenshot" in result["plan"]["command_plan"]
    assert audit_log.entries[-1]["action"] == "browser.task"
    assert audit_log.entries[-1]["allowed"] is True


def test_skill_tool_binding_skips_disabled_or_missing_runtime():
    disabled_skill = SkillRecord(
        skill_id="disabled",
        name="disabled",
        source_path=Path("skills/disabled/SKILL.md"),
        body="Run `disabled-cli do thing`.",
        enabled=False,
    )
    missing_skill = SkillRecord(
        skill_id="missing",
        name="missing",
        source_path=Path("skills/missing/SKILL.md"),
        body="Run `missing-cli do thing`.",
        enabled=True,
    )
    registry = ToolRegistry()

    SkillToolBindingService(command_exists=lambda command: False).register_bindings(
        registry,
        [disabled_skill, missing_skill],
    )

    assert registry.has("skill:disabled") is False
    assert registry.has("skill:missing") is False


def test_run_version_command_returns_structured_failure_when_command_missing():
    returncode, stdout, stderr = _run_version_command(
        ["definitely-missing-pmaa-command", "--version"],
        timeout_seconds=1,
    )

    assert returncode == -1
    assert stdout == ""
    assert "Command not found" in stderr
