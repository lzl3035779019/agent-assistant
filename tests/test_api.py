from fastapi.testclient import TestClient

from pmaa.main import app
from pmaa.schemas.task import AgentEvent, FinalResult, ReflectionResult
from pmaa.workflow.state import WorkflowResult


def test_run_workflow_api_returns_workflow_result(monkeypatch):
    captured = {}

    def fake_run_workflow(
        user_input: str,
        *,
        use_configured_llm: bool,
        use_configured_search: bool,
        conversation_context: str,
        enable_memory: bool,
        enable_skills: bool,
    ) -> WorkflowResult:
        captured.update(
            {
                "user_input": user_input,
                "use_configured_llm": use_configured_llm,
                "use_configured_search": use_configured_search,
                "conversation_context": conversation_context,
                "enable_memory": enable_memory,
                "enable_skills": enable_skills,
            }
        )
        return WorkflowResult(
            task_id="task-1",
            user_input=user_input,
            conversation_context=conversation_context,
            final_result=FinalResult(
                answer="API answer",
                sources=[],
                reflection=ReflectionResult(
                    passed=True,
                    issues=[],
                    suggested_fix="",
                    need_retry=False,
                ),
            ),
            events=[
                AgentEvent(
                    task_id="task-1",
                    agent="supervisor",
                    event_type="completed",
                    output={
                        "intent": "casual_chat",
                        "execution_mode": "direct_answer",
                    },
                )
            ],
        )

    monkeypatch.setattr("pmaa.api.routes.run_workflow", fake_run_workflow)
    client = TestClient(app)

    response = client.post(
        "/api/workflows/run",
        json={
            "user_input": "你好",
            "conversation_context": "上一轮：无",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "task-1"
    assert body["user_input"] == "你好"
    assert body["conversation_context"] == "上一轮：无"
    assert body["final_result"]["answer"] == "API answer"
    assert body["events"][0]["output"]["execution_mode"] == "direct_answer"
    assert captured == {
        "user_input": "你好",
        "use_configured_llm": True,
        "use_configured_search": True,
        "conversation_context": "上一轮：无",
        "enable_memory": True,
        "enable_skills": True,
    }


def test_create_task_returns_completed_workflow_result():
    client = TestClient(app)

    response = client.post(
        "/api/tasks",
        json={"user_input": "帮我研究 LangGraph 的核心概念，并生成学习路线"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["answer"]
    assert body["result"]["reflection"]["passed"] is True


def test_stream_workflow_api_returns_sse_events(monkeypatch):
    def fake_stream_workflow_events(
        user_input: str,
        *,
        use_configured_llm: bool,
        use_configured_search: bool,
        conversation_context: str,
        enable_memory: bool,
        enable_skills: bool,
    ):
        assert user_input == "hi"
        assert use_configured_llm is True
        assert use_configured_search is True
        assert conversation_context == ""
        assert enable_memory is True
        assert enable_skills is True
        yield {
            "type": "workflow_started",
            "task_id": "task-1",
            "user_input": "hi",
        }
        yield {
            "type": "agent_event",
            "task_id": "task-1",
            "event": AgentEvent(
                task_id="task-1",
                agent="supervisor",
                event_type="completed",
                output={"execution_mode": "direct_answer"},
            ),
        }
        yield {
            "type": "workflow_completed",
            "task_id": "task-1",
            "result": WorkflowResult(
                task_id="task-1",
                user_input="hi",
                final_result=FinalResult(
                    answer="hello",
                    sources=[],
                    reflection=ReflectionResult(
                        passed=True,
                        issues=[],
                        suggested_fix="",
                        need_retry=False,
                    ),
                ),
            ),
        }

    monkeypatch.setattr(
        "pmaa.api.routes.stream_workflow_events",
        fake_stream_workflow_events,
    )
    client = TestClient(app)

    response = client.post(
        "/api/workflows/stream",
        json={"user_input": "hi"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: workflow_started" in body
    assert "event: agent_event" in body
    assert "event: workflow_completed" in body
    assert '"agent":"supervisor"' in body


def test_confirm_action_api_returns_confirmation_result(monkeypatch):
    from pmaa.skills.executors import create_default_executor_registry

    opened_urls: list[str] = []
    monkeypatch.setattr(
        "pmaa.api.routes.create_default_executor_registry",
        lambda: create_default_executor_registry(
            browser_opener=lambda url: opened_urls.append(url) or True
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/api/actions/confirm",
        json={
            "pending_confirmation": {
                "status": "confirmation_required",
                "tool_name": "skill:agent_browser",
                "skill_id": "agent_browser",
                "action": "browser.open_url",
                "permission_level": "network",
                "requires_confirmation": True,
                "plan": {"url": "https://example.com"},
            },
            "approved": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is True
    assert body["status"] == "executed"
    assert body["execution"]["status"] == "executed"
    assert opened_urls == ["https://example.com"]
