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
