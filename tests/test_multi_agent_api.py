from fastapi.testclient import TestClient

from pmaa.main import app
from pmaa.schemas.task import AgentEvent, FinalResult, ReflectionResult
from pmaa.schemas.background_job import BackgroundJob
from pmaa.storage.background_job_store import SQLiteBackgroundJobStore
from pmaa.storage.daily_brief_store import SQLiteDailyBriefScheduleStore
from pmaa.workflow.state import WorkflowResult


def workflow_result(user_input: str) -> WorkflowResult:
    return WorkflowResult(
        task_id="multi-1",
        user_input=user_input,
        final_result=FinalResult(
            answer="Multi-agent answer",
            sources=[],
            reflection=ReflectionResult(passed=True),
        ),
        events=[
            AgentEvent(
                task_id="multi-1",
                agent="supervisor",
                event_type="decision_completed",
                output={"intent": "research", "mode": "delegate"},
            ),
            AgentEvent(
                task_id="multi-1",
                agent="web_research",
                event_type="task_completed",
                output={"status": "completed"},
            ),
        ],
    )


def test_multi_agent_run_endpoint(monkeypatch) -> None:
    captured = {}

    def fake_run(user_input: str, conversation_context: str = "") -> WorkflowResult:
        captured.update(
            {"user_input": user_input, "conversation_context": conversation_context}
        )
        return workflow_result(user_input)

    monkeypatch.setattr("pmaa.api.routes.run_multi_agent_workflow", fake_run)
    response = TestClient(app).post(
        "/api/multi-agent/run",
        json={"user_input": "研究 LangGraph", "conversation_context": "context"},
    )

    assert response.status_code == 200
    assert response.json()["final_result"]["answer"] == "Multi-agent answer"
    assert captured == {
        "user_input": "研究 LangGraph",
        "conversation_context": "context",
    }


def test_multi_agent_stream_endpoint(monkeypatch) -> None:
    def fake_stream(user_input: str, conversation_context: str = ""):
        yield {
            "type": "workflow_started",
            "task_id": "multi-1",
            "architecture": "hierarchical_multi_agent",
        }
        yield {
            "type": "agent_event",
            "task_id": "multi-1",
            "event": AgentEvent(
                task_id="multi-1",
                agent="web_research",
                event_type="task_started",
            ),
        }
        yield {
            "type": "workflow_completed",
            "task_id": "multi-1",
            "result": workflow_result(user_input),
        }

    monkeypatch.setattr(
        "pmaa.api.routes.stream_multi_agent_workflow_events", fake_stream
    )
    response = TestClient(app).post(
        "/api/multi-agent/stream",
        json={"user_input": "研究 LangGraph"},
    )

    assert response.status_code == 200
    assert "event: workflow_started" in response.text
    assert "event: agent_event" in response.text
    assert '"agent":"web_research"' in response.text
    assert "event: workflow_completed" in response.text


def test_background_job_and_daily_brief_schedule_api(monkeypatch, tmp_path) -> None:
    job_store = SQLiteBackgroundJobStore(tmp_path / "jobs.sqlite3")
    schedule_store = SQLiteDailyBriefScheduleStore(tmp_path / "automation.sqlite3")
    submitted = job_store.save(
        BackgroundJob(kind="chat", label="后台任务", request={"user_input": "测试"})
    )

    class FakeManager:
        def submit_multi_agent(self, **kwargs):
            return submitted.model_copy(update={"request": kwargs})

    class FakeScheduler:
        def __init__(self):
            self.started = False

        def start(self):
            self.started = True

    fake_scheduler = FakeScheduler()
    monkeypatch.setattr("pmaa.api.routes.background_job_store", job_store)
    monkeypatch.setattr("pmaa.api.routes.background_job_manager", FakeManager())
    monkeypatch.setattr("pmaa.api.routes.daily_brief_schedule_store", schedule_store)
    monkeypatch.setattr("pmaa.api.routes.scheduler_worker", fake_scheduler)
    monkeypatch.setattr(
        "pmaa.api.routes.submit_daily_brief_job",
        lambda trigger="manual", schedule=None: submitted.model_copy(
            update={"kind": "daily_brief", "label": schedule.name if schedule else "手动简报"}
        ),
    )
    client = TestClient(app)

    accepted = client.post(
        "/api/background-jobs/multi-agent",
        json={"user_input": "研究 Agent", "kind": "chat", "label": "研究"},
    )
    schedule = client.put(
        "/api/daily-brief/schedule",
        json={
            "enabled": True,
            "run_time": "07:30",
            "timezone": "Asia/Shanghai",
        },
    )
    manual = client.post("/api/daily-brief/run")
    created = client.post(
        "/api/daily-brief/schedules",
        json={
            "name": "晚间简报",
            "enabled": True,
            "run_time": "20:00",
            "timezone": "Asia/Shanghai",
        },
    )
    schedule_id = created.json()["schedule_id"]
    updated = client.put(
        f"/api/daily-brief/schedules/{schedule_id}",
        json={"name": "晚间技术简报", "run_time": "21:00"},
    )
    scheduled_manual = client.post(
        "/api/daily-brief/run",
        params={"schedule_id": schedule_id},
    )

    assert accepted.status_code == 200
    assert accepted.json()["job_id"] == submitted.job_id
    assert client.get(f"/api/background-jobs/{submitted.job_id}").status_code == 200
    assert schedule.json()["enabled"] is True
    assert schedule.json()["run_time"] == "07:30"
    assert fake_scheduler.started is True
    assert manual.json()["kind"] == "daily_brief"
    assert len(client.get("/api/daily-brief/schedules").json()) == 2
    assert updated.json()["name"] == "晚间技术简报"
    assert updated.json()["run_time"] == "21:00"
    assert scheduled_manual.json()["label"] == "晚间技术简报"
    assert client.delete(f"/api/daily-brief/schedules/{schedule_id}").status_code == 200
