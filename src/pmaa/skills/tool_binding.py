import subprocess
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from pmaa.schemas.skill import SkillRecord
from pmaa.skills.actions import (
    ActionAdapterRegistry,
    SkillActionRequest as AdapterActionRequest,
)
from pmaa.skills.runtime import SkillRuntimeInspector
from pmaa.tools.registry import ToolRegistry


SkillActionName = Literal["health_check"]
SkillPermissionLevel = Literal["safe", "network", "filesystem", "dangerous"]


class SkillActionRequest(BaseModel):
    action: str = "health_check"
    args: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class SkillActionLog:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def append(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)


class SkillToolBinding(BaseModel):
    skill_id: str
    tool_name: str
    command_name: str
    available: bool
    skill_name: str = ""
    description: str = ""
    supported_actions: list[str] = Field(default_factory=lambda: ["health_check"])


class SkillToolBindingService:
    def __init__(
        self,
        command_exists: Callable[[str], bool] | None = None,
        runner: Callable[[list[str], int], tuple[int, str, str]] | None = None,
        timeout_seconds: int = 60,
        audit_log: SkillActionLog | None = None,
        action_registry: ActionAdapterRegistry | None = None,
    ) -> None:
        self._command_exists = command_exists
        self._runner = runner or _run_version_command
        self._timeout_seconds = timeout_seconds
        self._audit_log = audit_log or SkillActionLog()
        self._action_registry = action_registry

    def bindings_for(self, skill: SkillRecord) -> list[SkillToolBinding]:
        report = SkillRuntimeInspector(command_exists=self._command_exists).inspect(skill)
        bindings: list[SkillToolBinding] = []
        for command in report.commands:
            adapter_actions = (
                self._action_registry.supported_actions_for_skill(
                    skill.name,
                    skill.description,
                )
                if self._action_registry is not None
                else []
            )
            bindings.append(
                SkillToolBinding(
                    skill_id=skill.skill_id,
                    tool_name=f"skill:{skill.skill_id}",
                    command_name=command.name,
                    available=command.available,
                    skill_name=skill.name,
                    description=skill.description,
                    supported_actions=["health_check", *adapter_actions],
                )
            )
        return bindings[:1]

    def register_bindings(
        self,
        registry: ToolRegistry,
        skills: list[SkillRecord],
    ) -> list[SkillToolBinding]:
        registered: list[SkillToolBinding] = []
        for skill in skills:
            if not skill.enabled:
                continue
            for binding in self.bindings_for(skill):
                if not binding.available:
                    continue
                registry.register(
                    binding.tool_name,
                    self._build_version_tool(binding),
                )
                registered.append(binding)
        return registered

    def _build_version_tool(self, binding: SkillToolBinding):
        def _tool(request: Any = None, *args, **kwargs) -> dict:
            action_request = _coerce_action_request(request)
            if action_request.action != "health_check" and self._action_registry is not None:
                return self._execute_adapter_action(binding, action_request)
            if action_request.action != "health_check":
                return self._reject_action(binding, action_request)

            command = [binding.command_name, "--version"]
            returncode, stdout, stderr = self._runner(command, self._timeout_seconds)
            result = {
                "success": returncode == 0,
                "tool_name": binding.tool_name,
                "skill_id": binding.skill_id,
                "action": "health_check",
                "supported_actions": binding.supported_actions,
                "permission_level": "safe",
                "requires_confirmation": False,
                "confirmed": action_request.confirmed,
                "command": command,
                "returncode": returncode,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "rollback": {
                    "status": "not_required",
                    "reason": "health_check is read-only.",
                },
            }
            self._audit_log.append(_audit_entry(binding, result, allowed=True))
            return result

        return _tool

    def _execute_adapter_action(
        self,
        binding: SkillToolBinding,
        action_request: SkillActionRequest,
    ) -> dict[str, Any]:
        if action_request.action not in binding.supported_actions:
            return self._reject_action(binding, action_request)
        result = self._action_registry.execute(
            AdapterActionRequest(
                action=action_request.action,
                args=action_request.args,
                confirmed=action_request.confirmed,
            )
        )
        result = {
            **result,
            "tool_name": binding.tool_name,
            "skill_id": binding.skill_id,
            "supported_actions": binding.supported_actions,
            "command": [],
            "returncode": 0 if result.get("status") == "confirmation_required" else -1,
            "stdout": "",
            "stderr": "",
        }
        self._audit_log.append(
            _audit_entry(
                binding,
                result,
                allowed=result.get("status") != "unsupported" and result.get("status") != "rejected",
            )
        )
        return result

    def _reject_action(
        self,
        binding: SkillToolBinding,
        action_request: SkillActionRequest,
    ) -> dict[str, Any]:
        result = {
            "success": False,
            "tool_name": binding.tool_name,
            "skill_id": binding.skill_id,
            "action": action_request.action,
            "supported_actions": binding.supported_actions,
            "permission_level": "dangerous",
            "requires_confirmation": True,
            "confirmed": action_request.confirmed,
            "command": [],
            "returncode": -1,
            "stdout": "",
            "stderr": "",
            "error": "Unsupported skill action.",
            "rollback": {
                "status": "not_started",
                "reason": "Action was rejected before execution.",
            },
        }
        self._audit_log.append(_audit_entry(binding, result, allowed=False))
        return result


def _coerce_action_request(request: Any) -> SkillActionRequest:
    if request is None or isinstance(request, str):
        return SkillActionRequest()
    if isinstance(request, SkillActionRequest):
        return request
    if isinstance(request, dict):
        return SkillActionRequest.model_validate(request)
    return SkillActionRequest()


def _audit_entry(
    binding: SkillToolBinding,
    result: dict[str, Any],
    *,
    allowed: bool,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "skill_id": binding.skill_id,
        "tool_name": binding.tool_name,
        "action": result["action"],
        "permission_level": result["permission_level"],
        "allowed": allowed,
        "command": result["command"],
        "returncode": result["returncode"],
        "rollback": result["rollback"],
    }


def _run_version_command(command: list[str], timeout_seconds: int) -> tuple[int, str, str]:
    if not command:
        return -1, "", "Command is empty."
    resolved_command = shutil.which(command[0])
    if resolved_command is None:
        return -1, "", f"Command not found: {command[0]}"
    completed = subprocess.run(
        [resolved_command, *command[1:]],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr
