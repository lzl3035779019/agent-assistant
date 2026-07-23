from __future__ import annotations

from typing import Annotated, Any

from typing_extensions import TypedDict

from pmaa.multi_agent.contracts import AgentResult, AgentTask, Evidence


def _merge_unique(left: dict[str, Any], right: dict[str, Any], label: str) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if key in merged and merged[key] != value:
            raise ValueError(f"Conflicting {label} for ID: {key}")
        merged[key] = value
    return merged


def merge_task_maps(
    left: dict[str, AgentTask], right: dict[str, AgentTask]
) -> dict[str, AgentTask]:
    return _merge_unique(left, right, "task")


def merge_result_maps(
    left: dict[str, AgentResult], right: dict[str, AgentResult]
) -> dict[str, AgentResult]:
    return _merge_unique(left, right, "result")


def merge_evidence_maps(
    left: dict[str, Evidence], right: dict[str, Evidence]
) -> dict[str, Evidence]:
    return _merge_unique(left, right, "evidence")


class MultiAgentGraphState(TypedDict, total=False):
    request_id: str
    user_input: str
    conversation_context: str
    supervisor_plan: dict[str, Any]
    tasks: Annotated[dict[str, AgentTask], merge_task_maps]
    results: Annotated[dict[str, AgentResult], merge_result_maps]
    evidence: Annotated[dict[str, Evidence], merge_evidence_maps]
    pending_actions: list[dict[str, Any]]
    final_answer: str
    errors: list[str]
