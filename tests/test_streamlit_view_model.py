from pmaa.ui.view_model import build_task_view
from pmaa.schemas.task import AgentEvent
from pmaa.workflow.state import WorkflowResult
from pmaa.workflow.graph import run_workflow


def test_build_task_view_contains_answer_sources_reflection_and_events():
    result = run_workflow("帮我研究 LangGraph 的核心概念，并生成学习路线")

    view = build_task_view(result)

    assert "LangGraph" in view["answer"]
    assert len(view["sources"]) == 2
    assert view["source_references"][0]["label"].startswith("[S1]")
    assert view["source_references"][0]["url"].startswith("https://")
    assert view["reflection"]["passed"] is True
    assert view["metrics"]["agent_count"] == 6
    assert view["metrics"]["source_count"] == 2
    assert view["metrics"]["reflection_status"] == "通过"
    assert view["metrics"]["llm_model"]
    assert [event["agent"] for event in view["events"]] == [
        "supervisor",
        "planner",
        "search",
        "tool",
        "writer",
        "reflection",
        "supervisor",
    ]
    assert [event["label"] for event in view["events"]] == [
        "Supervisor",
        "Planner",
        "Search",
        "Tool",
        "Writer",
        "Reflection",
        "Supervisor",
    ]


def test_build_task_view_exposes_pending_confirmation_without_final_result():
    result = WorkflowResult(
        user_input="Open https://example.com",
        pending_confirmation={
            "status": "confirmation_required",
            "action": "browser.open_url",
            "permission_level": "network",
            "plan": {"url": "https://example.com"},
        },
        events=[
            AgentEvent(
                task_id="task-1",
                agent="tool",
                event_type="completed",
                output={"tool_name": "skill:agent_browser"},
            ),
            AgentEvent(
                task_id="task-1",
                agent="supervisor",
                event_type="await_confirmation",
                output={"action": "browser.open_url"},
            ),
        ],
    )

    view = build_task_view(result)

    assert view["pending_confirmation"]["action"] == "browser.open_url"
    assert view["pending_confirmation"]["plan"]["url"] == "https://example.com"
    assert view["reflection"]["issues"] == ["Workflow is waiting for user confirmation."]
    assert [event["event_type"] for event in view["events"]] == [
        "completed",
        "await_confirmation",
    ]


def test_build_task_view_labels_multi_agent_events():
    result = WorkflowResult(
        user_input="研究主题",
        events=[
            AgentEvent(
                task_id="task-1",
                agent="web_research",
                event_type="task_completed",
            ),
            AgentEvent(
                task_id="task-1",
                agent="memory",
                event_type="task_completed",
            ),
        ],
    )

    view = build_task_view(result)

    assert [event["label"] for event in view["events"]] == [
        "Web Research Agent",
        "Memory Agent",
    ]
