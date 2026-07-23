from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from pmaa.multi_agent.contracts import AgentResult, AgentSpec, AgentTask


class AgentHandler(Protocol):
    def __call__(self, task: AgentTask, context: object) -> AgentResult: ...


class AgentRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, AgentSpec] = {}
        self._handlers: dict[str, AgentHandler] = {}

    def register(self, spec: AgentSpec, handler: AgentHandler) -> None:
        if spec.agent_id in self._specs:
            raise ValueError(f"Agent already registered: {spec.agent_id}")
        if not callable(handler):
            raise TypeError("Agent handler must be callable.")
        self._specs[spec.agent_id] = spec
        self._handlers[spec.agent_id] = handler

    def unregister(self, agent_id: str) -> None:
        self._specs.pop(agent_id, None)
        self._handlers.pop(agent_id, None)

    def get_spec(self, agent_id: str) -> AgentSpec:
        try:
            return self._specs[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown agent: {agent_id}") from exc

    def get_handler(self, agent_id: str) -> AgentHandler:
        self.get_spec(agent_id)
        return self._handlers[agent_id]

    def list_specs(self, *, enabled_only: bool = True) -> list[AgentSpec]:
        specs = list(self._specs.values())
        if enabled_only:
            specs = [spec for spec in specs if spec.enabled]
        return sorted(specs, key=lambda item: item.agent_id)

    def validate_task(self, task: AgentTask) -> AgentSpec:
        spec = self.get_spec(task.assigned_to)
        if not spec.enabled:
            raise ValueError(f"Agent is disabled: {task.assigned_to}")
        unauthorized = set(task.allowed_tools) - set(spec.allowed_tools)
        if unauthorized:
            names = ", ".join(sorted(unauthorized))
            raise ValueError(f"Agent {task.assigned_to} cannot use tools: {names}")
        if task.max_retries > spec.max_retries:
            raise ValueError(
                f"Task max_retries exceeds the limit for {task.assigned_to}."
            )
        return spec


AgentFactory = Callable[[], tuple[AgentSpec, AgentHandler]]
