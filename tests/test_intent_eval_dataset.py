from pathlib import Path

from pmaa.evaluation.intent_routing import (
    evaluate_intent_routing_cases,
    load_intent_routing_cases,
)


DATASET_PATH = Path("data/eval/intent_routing_cases.json")


def test_intent_routing_dataset_covers_core_mvp_scenarios():
    cases = load_intent_routing_cases(DATASET_PATH)
    categories = {case.category for case in cases}

    assert len(cases) >= 14
    assert {
        "casual_chat",
        "self_status",
        "memory_update",
        "realtime_query",
        "search_task",
        "research_task",
        "writing_task",
        "planning_task",
        "coding_task",
        "clarification",
        "follow_up",
    }.issubset(categories)


def test_intent_routing_dataset_passes_deterministic_evaluation():
    report = evaluate_intent_routing_cases(load_intent_routing_cases(DATASET_PATH))

    assert report.total >= 14
    assert report.failed == 0
    assert report.passed == report.total
    assert report.accuracy == 1.0
