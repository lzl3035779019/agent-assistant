import pytest

from pmaa.multi_agent.contracts import AgentResult, AgentStatus, AgentTask
from pmaa.multi_agent.state import merge_result_maps, merge_task_maps


def test_state_reducers_merge_distinct_branches() -> None:
    first = AgentTask(task_id="one", assigned_to="research", objective="One")
    second = AgentTask(task_id="two", assigned_to="memory", objective="Two")

    merged = merge_task_maps({first.task_id: first}, {second.task_id: second})

    assert set(merged) == {"one", "two"}


def test_state_reducers_accept_identical_replay() -> None:
    result = AgentResult(
        task_id="one",
        agent_id="research",
        status=AgentStatus.COMPLETED,
    )

    assert merge_result_maps({"one": result}, {"one": result}) == {"one": result}


def test_state_reducers_reject_conflicting_duplicate() -> None:
    first = AgentTask(task_id="one", assigned_to="research", objective="One")
    conflicting = first.model_copy(update={"objective": "Changed"})

    with pytest.raises(ValueError, match="Conflicting task"):
        merge_task_maps({"one": first}, {"one": conflicting})
