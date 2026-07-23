from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any

from pmaa.multi_agent.contracts import (
    AgentMessage,
    AgentResult,
    AgentStatus,
    AgentTask,
    Evidence,
)


@dataclass(frozen=True)
class BlackboardSnapshot:
    tasks: dict[str, AgentTask]
    statuses: dict[str, AgentStatus]
    messages: dict[str, list[AgentMessage]]
    results: dict[str, AgentResult]
    evidence: dict[str, list[Evidence]]
    artifacts: dict[str, dict[str, Any]]


class InMemoryBlackboard:
    """Central shared state. Child agents may only publish messages to Supervisor."""

    def __init__(self) -> None:
        self._tasks: dict[str, AgentTask] = {}
        self._statuses: dict[str, AgentStatus] = {}
        self._messages: dict[str, list[AgentMessage]] = defaultdict(list)
        self._results: dict[str, AgentResult] = {}
        self._evidence: dict[str, list[Evidence]] = defaultdict(list)
        self._artifacts: dict[str, dict[str, Any]] = defaultdict(dict)
        self._lock = RLock()

    def add_task(self, task: AgentTask) -> None:
        with self._lock:
            if task.task_id in self._tasks:
                raise ValueError(f"Task already exists: {task.task_id}")
            missing = [task_id for task_id in task.depends_on if task_id not in self._tasks]
            if missing:
                raise ValueError(f"Unknown task dependencies: {', '.join(missing)}")
            self._tasks[task.task_id] = task
            self._statuses[task.task_id] = AgentStatus.PENDING

    def has_task(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._tasks

    def get_task(self, task_id: str) -> AgentTask:
        with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as exc:
                raise KeyError(f"Unknown task: {task_id}") from exc

    def set_status(self, task_id: str, status: AgentStatus) -> None:
        with self._lock:
            self.get_task(task_id)
            self._statuses[task_id] = status

    def get_status(self, task_id: str) -> AgentStatus:
        with self._lock:
            self.get_task(task_id)
            return self._statuses[task_id]

    def add_message(self, message: AgentMessage) -> None:
        if message.receiver != "supervisor":
            raise ValueError("Child agents may only send messages to supervisor.")
        with self._lock:
            self.get_task(message.task_id)
            self._messages[message.task_id].append(message)

    def list_messages(self, task_id: str) -> list[AgentMessage]:
        with self._lock:
            self.get_task(task_id)
            return deepcopy(self._messages[task_id])

    def add_evidence(self, item: Evidence) -> None:
        with self._lock:
            task = self.get_task(item.task_id)
            if item.agent_id != task.assigned_to:
                raise ValueError("Evidence agent does not match the assigned agent.")
            self._evidence[item.task_id].append(item)

    def list_evidence(self, task_id: str) -> list[Evidence]:
        with self._lock:
            self.get_task(task_id)
            return deepcopy(self._evidence[task_id])

    def put_artifact(self, task_id: str, name: str, value: Any) -> None:
        """Publish a Supervisor-owned tool result for a waiting child task."""
        if not name.strip():
            raise ValueError("Artifact name cannot be empty.")
        with self._lock:
            self.get_task(task_id)
            self._artifacts[task_id][name] = deepcopy(value)

    def get_artifacts(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            self.get_task(task_id)
            return deepcopy(self._artifacts[task_id])

    def add_result(self, result: AgentResult) -> None:
        with self._lock:
            task = self.get_task(result.task_id)
            if result.agent_id != task.assigned_to:
                raise ValueError("Result agent does not match the assigned agent.")
            if result.task_id in self._results:
                raise ValueError(f"Task result already exists: {result.task_id}")
            self._results[result.task_id] = result
            self._statuses[result.task_id] = result.status
            for item in result.evidence:
                self.add_evidence(item)

    def get_result(self, task_id: str) -> AgentResult | None:
        with self._lock:
            self.get_task(task_id)
            result = self._results.get(task_id)
            return deepcopy(result) if result else None

    def dependencies_completed(self, task: AgentTask) -> bool:
        with self._lock:
            return all(
                self._statuses.get(task_id) in {AgentStatus.COMPLETED, AgentStatus.PARTIAL}
                for task_id in task.depends_on
            )

    def snapshot(self) -> BlackboardSnapshot:
        with self._lock:
            return BlackboardSnapshot(
                tasks=deepcopy(self._tasks),
                statuses=deepcopy(self._statuses),
                messages=deepcopy(dict(self._messages)),
                results=deepcopy(self._results),
                evidence=deepcopy(dict(self._evidence)),
                artifacts=deepcopy(dict(self._artifacts)),
            )
