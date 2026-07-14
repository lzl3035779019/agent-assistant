import re
import shlex
import shutil
import subprocess
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from pmaa.schemas.skill import SkillRecord


RuntimeStatus = Literal["ready", "missing", "no_runtime"]


class RuntimeCommand(BaseModel):
    name: str
    examples: list[str] = Field(default_factory=list)
    available: bool = False


class SkillRuntimeReport(BaseModel):
    skill_id: str
    status: RuntimeStatus
    commands: list[RuntimeCommand] = Field(default_factory=list)
    install_commands: list[str] = Field(default_factory=list)


class SkillInstallResult(BaseModel):
    success: bool
    command: str = ""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class SkillRuntimeInspector:
    def __init__(
        self,
        command_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self._command_exists = command_exists or (lambda command: shutil.which(command) is not None)

    def inspect(self, skill: SkillRecord) -> SkillRuntimeReport:
        command_examples = _extract_command_examples(skill.body)
        command_names = _command_names(command_examples)
        commands = [
            RuntimeCommand(
                name=name,
                examples=[
                    command for command in command_examples if _first_command_name(command) == name
                ][:3],
                available=self._command_exists(name),
            )
            for name in command_names
        ]
        install_commands = [
            command
            for command in command_examples
            if command.startswith(("npm ", "pnpm ", "bun ", "pip ", "uv "))
            and any(token in command for token in [" install", " add", " i "])
        ]
        if not commands:
            status: RuntimeStatus = "no_runtime"
        elif all(command.available for command in commands):
            status = "ready"
        else:
            status = "missing"
        return SkillRuntimeReport(
            skill_id=skill.skill_id,
            status=status,
            commands=commands,
            install_commands=install_commands,
        )


class SkillRuntimeInstaller:
    def __init__(
        self,
        runner: Callable[[str, int], tuple[int, str, str]] | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self._runner = runner or _run_command
        self._timeout_seconds = timeout_seconds

    def install(self, skill: SkillRecord, command_index: int = 0) -> SkillInstallResult:
        report = SkillRuntimeInspector().inspect(skill)
        if command_index < 0 or command_index >= len(report.install_commands):
            return SkillInstallResult(
                success=False,
                returncode=-1,
                stderr="Invalid install command index.",
            )
        command = report.install_commands[command_index]
        returncode, stdout, stderr = self._runner(command, self._timeout_seconds)
        return SkillInstallResult(
            success=returncode == 0,
            command=command,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )


def _run_command(command: str, timeout_seconds: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _extract_command_examples(body: str) -> list[str]:
    commands: list[str] = []
    for fenced in re.findall(r"```(?:bash|shell|sh)?\s*(.*?)```", body, flags=re.DOTALL):
        for line in fenced.splitlines():
            command = _normalize_command_line(line)
            if command:
                commands.append(command)
    for inline in re.findall(r"`([^`\n]+)`", body):
        command = _normalize_command_line(inline)
        if command:
            commands.append(command)
    return _unique(commands)


def _normalize_command_line(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    stripped = stripped.removeprefix("$").strip()
    first = _first_command_name(stripped)
    if not first or first in {"cd", "echo", "cat", "export"}:
        return ""
    return stripped


def _command_names(commands: list[str]) -> list[str]:
    names: list[str] = []
    for command in commands:
        name = _first_command_name(command)
        if name and name not in names:
            names.append(name)
    return names


def _first_command_name(command: str) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.split()
    if not parts:
        return ""
    first = parts[0]
    if first in {"sudo", "uvx", "npx", "pnpm", "bunx"} and len(parts) > 1:
        return parts[1]
    return first


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item not in seen:
            output.append(item)
            seen.add(item)
    return output
