from pathlib import Path

from pmaa.schemas.skill import SkillRecord
from pmaa.skills.runtime import SkillRuntimeInstaller, SkillRuntimeInspector


def test_runtime_inspector_extracts_cli_commands_from_skill_body():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        description="Browser automation CLI for AI agents.",
        triggers=["browser"],
        enabled=True,
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="""
Install: `npm i -g agent-browser && agent-browser install`

```bash
agent-browser skills get core
agent-browser skills get core --full
```
""",
    )

    report = SkillRuntimeInspector().inspect(skill)

    command_names = [command.name for command in report.commands]
    assert set(command_names) == {"npm", "agent-browser"}
    assert report.install_commands == ["npm i -g agent-browser && agent-browser install"]


def test_runtime_inspector_checks_command_availability():
    skill = SkillRecord(
        skill_id="browser",
        name="browser",
        source_path=Path("skills/browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
    )
    checks = {"agent-browser": False}

    report = SkillRuntimeInspector(command_exists=lambda command: checks[command]).inspect(skill)

    assert report.status == "missing"
    assert report.commands[0].name == "agent-browser"
    assert report.commands[0].available is False


def test_runtime_inspector_marks_skill_ready_when_all_commands_exist():
    skill = SkillRecord(
        skill_id="browser",
        name="browser",
        source_path=Path("skills/browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
    )

    report = SkillRuntimeInspector(command_exists=lambda command: True).inspect(skill)

    assert report.status == "ready"
    assert report.commands[0].available is True


def test_runtime_installer_runs_declared_install_command():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Install: `npm i -g agent-browser && agent-browser install`",
    )
    executed: list[str] = []

    def fake_runner(command: str, timeout: int):
        executed.append(command)
        return 0, "installed", ""

    result = SkillRuntimeInstaller(runner=fake_runner).install(skill, 0)

    assert executed == ["npm i -g agent-browser && agent-browser install"]
    assert result.success is True
    assert result.returncode == 0
    assert result.stdout == "installed"


def test_runtime_installer_rejects_unknown_install_command_index():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="Install: `npm i -g agent-browser`",
    )

    result = SkillRuntimeInstaller(runner=lambda command, timeout: (0, "", "")).install(skill, 2)

    assert result.success is False
    assert result.returncode == -1
    assert "Invalid install command index" in result.stderr
