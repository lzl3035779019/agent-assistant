from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field


PermissionLevel = Literal["safe", "network", "filesystem", "dangerous"]


class SkillActionRequest(BaseModel):
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class SkillActionAdapter(BaseModel):
    action: str
    description: str
    permission_level: PermissionLevel
    requires_confirmation: bool
    input_schema: dict[str, Any] = Field(default_factory=dict)
    skill_terms: list[str] = Field(default_factory=list)


class ActionAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SkillActionAdapter] = {}
        self._handlers: dict[str, Callable[[SkillActionRequest], dict[str, Any]]] = {}

    def register(
        self,
        adapter: SkillActionAdapter,
        handler: Callable[[SkillActionRequest], dict[str, Any]],
    ) -> None:
        self._adapters[adapter.action] = adapter
        self._handlers[adapter.action] = handler

    def get(self, action: str) -> SkillActionAdapter | None:
        return self._adapters.get(action)

    def supported_actions_for_skill(self, skill_name: str, description: str) -> list[str]:
        searchable = f"{skill_name} {description}".lower()
        actions: list[str] = []
        for adapter in self._adapters.values():
            if any(term in searchable for term in adapter.skill_terms):
                actions.append(adapter.action)
        return actions

    def execute(self, request: SkillActionRequest) -> dict[str, Any]:
        adapter = self.get(request.action)
        if adapter is None:
            return {
                "success": False,
                "status": "unsupported",
                "action": request.action,
                "permission_level": "dangerous",
                "requires_confirmation": True,
                "confirmed": request.confirmed,
                "error": "Unsupported skill action.",
                "rollback": {
                    "status": "not_started",
                    "reason": "Action was rejected before execution.",
                },
            }
        return self._handlers[request.action](request)


def create_default_action_registry() -> ActionAdapterRegistry:
    registry = ActionAdapterRegistry()
    registry.register(
        SkillActionAdapter(
            action="browser.open_url",
            description="Prepare a browser navigation plan for an http or https URL.",
            permission_level="network",
            requires_confirmation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The http or https URL to open.",
                    }
                },
                "required": ["url"],
            },
            skill_terms=["browser", "web", "page", "url"],
        ),
        _browser_open_url,
    )
    registry.register(
        SkillActionAdapter(
            action="browser.task",
            description="Prepare a multi-step agent-browser automation task.",
            permission_level="network",
            requires_confirmation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The browser automation goal.",
                    },
                    "start_url": {
                        "type": "string",
                        "description": "Optional http or https URL where the task should start.",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "High-level browser steps inferred from the user request.",
                    },
                },
                "required": ["goal"],
            },
            skill_terms=[
                "browser",
                "web",
                "page",
                "url",
                "automation",
                "screenshot",
                "click",
                "fill",
                "scrape",
                "inspect",
                "test",
            ],
        ),
        _browser_task,
    )
    return registry


def _browser_open_url(request: SkillActionRequest) -> dict[str, Any]:
    url = str(request.args.get("url", "")).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "success": False,
            "status": "rejected",
            "action": "browser.open_url",
            "permission_level": "network",
            "requires_confirmation": True,
            "confirmed": request.confirmed,
            "dry_run": True,
            "error": "Only http and https URLs are allowed.",
            "rollback": {
                "status": "not_started",
                "reason": "Invalid URL rejected before execution.",
            },
        }
    return {
        "success": False,
        "status": "confirmation_required",
        "action": "browser.open_url",
        "permission_level": "network",
        "requires_confirmation": True,
        "confirmed": request.confirmed,
        "dry_run": True,
        "plan": {
            "operation": "open_url",
            "url": url,
        },
        "rollback": {
            "status": "not_started",
            "reason": "Dry-run plan only; no browser action executed.",
        },
    }


def _browser_task(request: SkillActionRequest) -> dict[str, Any]:
    goal = str(request.args.get("goal", "")).strip()
    start_url = str(request.args.get("start_url", "") or "").strip()
    if not goal:
        return {
            "success": False,
            "status": "rejected",
            "action": "browser.task",
            "permission_level": "network",
            "requires_confirmation": True,
            "confirmed": request.confirmed,
            "dry_run": True,
            "error": "Browser task goal is required.",
            "rollback": {
                "status": "not_started",
                "reason": "Invalid browser task rejected before execution.",
            },
        }
    if start_url:
        parsed = urlparse(start_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {
                "success": False,
                "status": "rejected",
                "action": "browser.task",
                "permission_level": "network",
                "requires_confirmation": True,
                "confirmed": request.confirmed,
                "dry_run": True,
                "error": "Only http and https start URLs are allowed.",
                "rollback": {
                    "status": "not_started",
                    "reason": "Invalid browser task rejected before execution.",
                },
            }
    steps = request.args.get("steps", [])
    if not isinstance(steps, list):
        steps = []
    normalized_steps = [str(step).strip() for step in steps if str(step).strip()]
    command_plan = _build_browser_task_command_plan(goal, start_url, normalized_steps)
    return {
        "success": False,
        "status": "confirmation_required",
        "action": "browser.task",
        "permission_level": "network",
        "requires_confirmation": True,
        "confirmed": request.confirmed,
        "dry_run": True,
        "plan": {
            "operation": "browser_task",
            "goal": goal,
            "start_url": start_url,
            "steps": normalized_steps,
            "command_plan": command_plan,
        },
        "rollback": {
            "status": "not_started",
            "reason": "Dry-run plan only; no browser action executed.",
        },
    }


def _build_browser_task_command_plan(
    goal: str,
    start_url: str,
    steps: list[str],
) -> list[str]:
    commands: list[str] = []
    searchable = " ".join([goal, *steps]).lower()
    if start_url:
        commands.append(f"agent-browser open {start_url}")
    if any(marker in searchable for marker in ("截图", "screenshot", "capture")):
        commands.append("agent-browser screenshot")
    if any(marker in searchable for marker in ("抽取", "提取", "读取", "read", "extract", "scrape")):
        commands.append("agent-browser read")
    if any(marker in searchable for marker in ("点击", "click")):
        commands.append("agent-browser snapshot -i")
        commands.append("agent-browser click <ref>")
    if any(marker in searchable for marker in ("填写", "填表", "fill", "form")):
        commands.append("agent-browser snapshot -i")
        commands.append("agent-browser fill <ref> <value>")
    if not commands:
        commands.append("agent-browser snapshot -i")
    return commands
