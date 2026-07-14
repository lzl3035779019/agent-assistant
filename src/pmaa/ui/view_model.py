from typing import Any

from pmaa.config import settings
from pmaa.workflow.state import WorkflowResult


AGENT_LABELS = {
    "supervisor": "Supervisor",
    "knowledge": "Knowledge",
    "planner": "Planner",
    "search": "Search",
    "tool": "Tool",
    "writer": "Writer",
    "reflection": "Reflection",
}


def build_source_references(sources: list) -> list[dict[str, str]]:
    return [
        {
            **source.model_dump(),
            "label": f"[S{index}] {source.title}",
        }
        for index, source in enumerate(sources, start=1)
    ]


def build_task_view(result: WorkflowResult) -> dict[str, Any]:
    final_result = result.final_result
    if final_result is None:
        events = [
            {
                "agent": event.agent,
                "label": AGENT_LABELS.get(event.agent, event.agent.title()),
                "event_type": event.event_type,
                "output": event.output,
                "timestamp": event.timestamp.isoformat(),
            }
            for event in result.events
        ]
        if result.pending_confirmation:
            unique_agents = {
                event.agent
                for event in result.events
                if event.agent in AGENT_LABELS
            }
            return {
                "answer": "",
                "sources": [],
                "source_references": [],
                "action_audit": [],
                "pending_confirmation": result.pending_confirmation,
                "reflection": {
                    "passed": False,
                    "issues": ["Workflow is waiting for user confirmation."],
                },
                "metrics": {
                    "agent_count": len(unique_agents),
                    "source_count": 0,
                    "reflection_status": "等待确认",
                    "llm_model": settings.llm_model,
                },
                "events": events,
            }
        return {
            "answer": "",
            "sources": [],
            "source_references": [],
            "action_audit": [],
            "pending_confirmation": {},
            "reflection": {"passed": False, "issues": ["Workflow did not return a result."]},
            "metrics": {
                "agent_count": 0,
                "source_count": 0,
                "reflection_status": "未通过",
                "llm_model": settings.llm_model,
            },
            "events": events,
        }

    unique_agents = {
        event.agent
        for event in result.events
        if event.agent in AGENT_LABELS
    }
    reflection_status = "通过" if final_result.reflection.passed else "未通过"

    return {
        "answer": final_result.answer,
        "sources": [source.model_dump() for source in final_result.sources],
        "source_references": build_source_references(final_result.sources),
        "action_audit": [],
        "pending_confirmation": result.pending_confirmation,
        "reflection": final_result.reflection.model_dump(),
        "metrics": {
            "agent_count": len(unique_agents),
            "source_count": len(final_result.sources),
            "reflection_status": reflection_status,
            "llm_model": settings.llm_model,
        },
        "events": [
            {
                "agent": event.agent,
                "label": AGENT_LABELS.get(event.agent, event.agent.title()),
                "event_type": event.event_type,
                "output": event.output,
                "timestamp": event.timestamp.isoformat(),
            }
            for event in result.events
        ],
    }
