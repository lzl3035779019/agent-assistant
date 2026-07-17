from pathlib import Path
from subprocess import CompletedProcess

from pmaa.schemas.skill import SkillRecord
import pmaa.skills.runtime as runtime_module
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


def test_runtime_inspector_ignores_refs_urls_and_doc_fragments():
    skill = SkillRecord(
        skill_id="agent_browser",
        name="agent-browser",
        description="Browser automation CLI for AI agents.",
        source_path=Path("skills/agent_browser/SKILL.md"),
        body="""
Refs use `@eN`.
Dashboard: `https://dashboard.agent-browser.localhost`.
The prose may mention `skills get core`.

Install: `npm i -g agent-browser && agent-browser install`

```bash
agent-browser skills get core             # start here
agent-browser skills get core --full      # include full command reference
```
""",
    )

    report = SkillRuntimeInspector(
        command_exists=lambda command: command in {"npm", "agent-browser"}
    ).inspect(skill)

    assert [command.name for command in report.commands] == ["agent-browser", "npm"]
    assert report.status == "ready"
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


def test_default_runtime_check_requires_command_to_execute(monkeypatch):
    skill = SkillRecord(
        skill_id="browser",
        name="browser",
        source_path=Path("skills/browser/SKILL.md"),
        body="Run `agent-browser skills get core`.",
    )

    monkeypatch.setattr(runtime_module.shutil, "which", lambda command: f"C:/fake/{command}.cmd")

    def fake_run(*args, **kwargs):
        return CompletedProcess(args=args, returncode=1, stdout="", stderr="not installed")

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)

    report = SkillRuntimeInspector().inspect(skill)

    assert report.status == "missing"
    assert report.commands[0].available is False


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


def test_runtime_runner_translates_and_chain_for_windows_powershell(monkeypatch):
    captured: dict[str, list[str]] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)

    returncode, stdout, stderr = runtime_module._run_command(
        "npm i -g agent-browser && agent-browser install",
        10,
    )

    script = captured["args"][-1]
    assert returncode == 0
    assert stdout == "ok"
    assert stderr == ""
    assert "&&" not in script
    assert "npm i -g agent-browser" in script
    assert "agent-browser install" in script
    assert "if ($LASTEXITCODE -ne 0)" in script


def test_runtime_runner_injects_local_proxy_when_port_is_open(monkeypatch):
    captured: dict[str, dict[str, str]] = {}

    monkeypatch.delenv("PMAA_RUNTIME_PROXY_URL", raising=False)
    monkeypatch.delenv("PMAA_PROXY_URL", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.setattr(runtime_module, "_is_local_port_open", lambda port: port == 7897)

    def fake_run(args, **kwargs):
        captured["env"] = kwargs["env"]
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)

    runtime_module._run_command("npm i -g agent-browser", 10)

    assert captured["env"]["HTTPS_PROXY"] == "http://127.0.0.1:7897"
    assert captured["env"]["npm_config_https_proxy"] == "http://127.0.0.1:7897"
