from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pmaa.multi_agent.blackboard import InMemoryBlackboard
from pmaa.multi_agent.contracts import (
    AgentMessage,
    AgentMessageType,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from pmaa.multi_agent.registry import AgentRegistry


@dataclass
class AgentExecutionContext:
    task: AgentTask
    blackboard: InMemoryBlackboard

    def emit(self, message_type: AgentMessageType, content: dict[str, Any]) -> None:
        self.blackboard.add_message(
            AgentMessage(
                task_id=self.task.task_id,
                sender=self.task.assigned_to,
                receiver="supervisor",
                message_type=message_type,
                content=content,
            )
        )

    def report_progress(self, stage: str, **details: Any) -> None:
        self.emit(AgentMessageType.TASK_PROGRESS, {"stage": stage, **details})

    def request_delegation(
        self,
        *,
        target_capability: str,
        objective: str,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.emit(
            AgentMessageType.DELEGATION_REQUEST,
            {
                "target_capability": target_capability,
                "objective": objective,
                "reason": reason,
                "context": context or {},
            },
        )

    def request_retry(self, reason: str, *, retryable: bool = True) -> None:
        self.emit(
            AgentMessageType.RETRY_REQUEST,
            {"reason": reason, "retryable": retryable},
        )


class CentralAgentRuntime:
    def __init__(
        self,
        registry: AgentRegistry,
        blackboard: InMemoryBlackboard | None = None,
        *,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1.")
        self.registry = registry
        self.blackboard = blackboard or InMemoryBlackboard()
        self.max_concurrency = max_concurrency

    def dispatch(self, task: AgentTask) -> AgentResult:
        self.registry.validate_task(task)
        if self.blackboard.has_task(task.task_id):
            if self.blackboard.get_task(task.task_id) != task:
                raise ValueError(f"Task ID already belongs to another task: {task.task_id}")
            if self.blackboard.get_result(task.task_id) is not None:
                raise ValueError(f"Task was already completed: {task.task_id}")
        else:
            self.blackboard.add_task(task)
        if not self.blackboard.dependencies_completed(task):
            self.blackboard.set_status(task.task_id, AgentStatus.WAITING_DEPENDENCY)
            raise RuntimeError("Task dependencies are not completed.")

        started_at = datetime.now(timezone.utc)
        self.blackboard.set_status(task.task_id, AgentStatus.RUNNING)
        context = AgentExecutionContext(task=task, blackboard=self.blackboard)
        context.report_progress("started")

        try:
            handler = self.registry.get_handler(task.assigned_to)
            result = handler(task, context)
            self._validate_result(task, result)
        except Exception as exc:  # Runtime boundary must convert agent failures.
            result = AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_to,
                status=AgentStatus.FAILED,
                summary="Agent execution failed.",
                errors=[str(exc)],
                started_at=started_at,
            )
            context.emit(AgentMessageType.ERROR, {"error": str(exc)})

        if result.started_at is None:
            result = result.model_copy(update={"started_at": started_at})
        if result.status == AgentStatus.WAITING_DEPENDENCY:
            self.blackboard.set_status(task.task_id, AgentStatus.WAITING_DEPENDENCY)
            context.report_progress("suspended", status=result.status.value)
            return result
        self.blackboard.add_result(result)
        context.report_progress("finished", status=result.status.value)
        return result

    def dispatch_parallel(self, tasks: list[AgentTask]) -> list[AgentResult]:
        if not tasks:
            return []
        task_ids = [task.task_id for task in tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Parallel tasks must have unique task IDs.")
        unresolved = [
            task.task_id
            for task in tasks
            if task.depends_on and not self.blackboard.dependencies_completed(task)
        ]
        if unresolved:
            raise ValueError(
                "Parallel tasks must be independent or have completed dependencies: "
                + ", ".join(unresolved)
            )

        workers = min(self.max_concurrency, len(tasks))
        results: dict[str, AgentResult] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_task = {executor.submit(self.dispatch, task): task for task in tasks}
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                results[task.task_id] = future.result()
        return [results[task.task_id] for task in tasks]

    @staticmethod
    def _validate_result(task: AgentTask, result: AgentResult) -> None:
        if result.task_id != task.task_id:
            raise ValueError("Agent returned a result for another task.")
        if result.agent_id != task.assigned_to:
            raise ValueError("Agent result identity does not match the assignment.")
        if result.status not in {
            AgentStatus.COMPLETED,
            AgentStatus.PARTIAL,
            AgentStatus.FAILED,
            AgentStatus.WAITING_DEPENDENCY,
            AgentStatus.WAITING_CONFIRMATION,
        }:
            raise ValueError(f"Agent returned a non-final status: {result.status}")

    @staticmethod
    def _failure(task: AgentTask, error: str) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id=task.assigned_to,
            status=AgentStatus.FAILED,
            summary=error,
            errors=[error],
        )
