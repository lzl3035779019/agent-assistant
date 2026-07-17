import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pmaa.agents.supervisor import IntentDecision, SupervisorAgent
from pmaa.llm.client import LLMMessage


DEFAULT_DATASET_PATH = Path("data/eval/intent_routing_cases.json")
ROUTING_FIELDS = [
    "intent",
    "task_kind",
    "execution_mode",
    "need_memory",
    "need_tools",
    "required_tool",
    "should_plan",
]


class ExpectedRoutingDecision(BaseModel):
    intent: str
    task_kind: str
    execution_mode: str
    need_memory: bool = False
    need_tools: bool
    required_tool: str = "none"
    should_plan: bool


class IntentRoutingCase(BaseModel):
    case_id: str
    category: str
    user_input: str
    expected: ExpectedRoutingDecision
    conversation_context: str = ""
    llm_decision: ExpectedRoutingDecision | None = None
    rationale: str = ""


class IntentRoutingCaseResult(BaseModel):
    case_id: str
    category: str
    passed: bool
    mismatches: dict[str, dict[str, Any]] = Field(default_factory=dict)
    actual: dict[str, Any]
    expected: dict[str, Any]


class IntentRoutingReport(BaseModel):
    total: int
    passed: int
    failed: int
    accuracy: float
    results: list[IntentRoutingCaseResult]


class _CaseLLMClient:
    def __init__(self, decision: ExpectedRoutingDecision) -> None:
        self._decision = decision

    def complete_text(self, messages: list[LLMMessage]) -> str:
        return "评测用直接回答。"

    def complete_json(self, messages: list[LLMMessage]) -> dict[str, Any]:
        payload = self._decision.model_dump()
        payload["confidence"] = 0.95
        payload["reason"] = "deterministic_eval_case"
        return payload


def load_intent_routing_cases(
    path: str | Path = DEFAULT_DATASET_PATH,
) -> list[IntentRoutingCase]:
    dataset_path = Path(path)
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Intent routing dataset must be a JSON array.")
    return [IntentRoutingCase.model_validate(item) for item in payload]


def evaluate_intent_routing_case(case: IntentRoutingCase) -> IntentRoutingCaseResult:
    llm_client = _CaseLLMClient(case.llm_decision) if case.llm_decision else None
    decision = SupervisorAgent(llm_client=llm_client).classify_intent(
        case.user_input,
        conversation_context=case.conversation_context,
    )
    actual = _decision_subset(decision)
    expected = case.expected.model_dump()
    mismatches = {
        field: {"expected": expected[field], "actual": actual[field]}
        for field in ROUTING_FIELDS
        if actual[field] != expected[field]
    }
    return IntentRoutingCaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=not mismatches,
        mismatches=mismatches,
        actual=actual,
        expected=expected,
    )


def evaluate_intent_routing_cases(
    cases: list[IntentRoutingCase] | None = None,
) -> IntentRoutingReport:
    active_cases = cases if cases is not None else load_intent_routing_cases()
    results = [evaluate_intent_routing_case(case) for case in active_cases]
    passed = len([result for result in results if result.passed])
    total = len(results)
    return IntentRoutingReport(
        total=total,
        passed=passed,
        failed=total - passed,
        accuracy=round(passed / total, 4) if total else 0.0,
        results=results,
    )


def _decision_subset(decision: IntentDecision) -> dict[str, Any]:
    payload = decision.model_dump()
    return {field: payload[field] for field in ROUTING_FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PMAA intent routing evaluation.")
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET_PATH),
        help="Path to intent routing JSON dataset.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON report.",
    )
    args = parser.parse_args()

    report = evaluate_intent_routing_cases(load_intent_routing_cases(args.dataset))
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(
            f"Intent routing eval: {report.passed}/{report.total} passed "
            f"({report.accuracy:.2%})"
        )
        for result in report.results:
            status = "PASS" if result.passed else "FAIL"
            print(f"- {status} {result.case_id} [{result.category}]")
            if result.mismatches:
                print(f"  mismatches: {json.dumps(result.mismatches, ensure_ascii=False)}")
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
