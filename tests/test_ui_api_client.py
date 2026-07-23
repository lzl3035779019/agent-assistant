import httpx
import pytest

from pmaa.ui.api_client import (
    WorkflowAPIError,
    confirm_action_via_api,
    create_daily_brief_schedule_via_api,
    delete_daily_brief_schedule_via_api,
    parse_sse_messages,
    get_background_job_via_api,
    get_monitor_latest_result_via_api,
    list_daily_brief_schedules_via_api,
    run_daily_brief_now_via_api,
    run_multi_agent_via_api,
    run_workflow_via_api,
    submit_multi_agent_job_via_api,
    update_daily_brief_schedule_by_id_via_api,
)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://test/api/workflows/run")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("bad response", request=request, response=response)

    def json(self) -> dict:
        return self._payload


def test_run_workflow_via_api_returns_workflow_result(monkeypatch):
    captured = {}

    def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(
            {
                "task_id": "task-1",
                "user_input": "你好",
                "conversation_context": "上下文",
                "plan": None,
                "sources": [],
                "draft_answer": "",
                "final_result": {
                    "answer": "你好，我是 PMAA。",
                    "sources": [],
                    "reflection": {
                        "passed": True,
                        "issues": [],
                        "suggested_fix": "",
                        "need_retry": False,
                    },
                },
                "events": [],
            }
        )

    monkeypatch.setattr("httpx.post", fake_post)

    result = run_workflow_via_api("你好", "上下文", api_base_url="http://test")

    assert result.task_id == "task-1"
    assert result.final_result is not None
    assert result.final_result.answer == "你好，我是 PMAA。"
    assert captured == {
        "url": "http://test/api/workflows/run",
        "json": {
            "user_input": "你好",
            "conversation_context": "上下文",
        },
        "timeout": 120.0,
    }


def test_run_workflow_via_api_raises_clear_error(monkeypatch):
    def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
        return FakeResponse({}, status_code=500)

    monkeypatch.setattr("httpx.post", fake_post)

    with pytest.raises(WorkflowAPIError, match="FastAPI 工作流接口调用失败"):
        run_workflow_via_api("你好", api_base_url="http://test")


def test_run_multi_agent_via_api_uses_new_endpoint(monkeypatch):
    captured = {}

    def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(
            {
                "task_id": "multi-1",
                "user_input": "研究 LangGraph",
                "conversation_context": "",
                "plan": None,
                "sources": [],
                "draft_answer": "answer",
                "final_result": {
                    "answer": "answer",
                    "sources": [],
                    "reflection": {
                        "passed": True,
                        "issues": [],
                        "suggested_fix": "",
                        "need_retry": False,
                    },
                },
                "events": [],
            }
        )

    monkeypatch.setattr("httpx.post", fake_post)

    result = run_multi_agent_via_api(
        "研究 LangGraph",
        api_base_url="http://test",
    )

    assert result.task_id == "multi-1"
    assert captured["url"] == "http://test/api/multi-agent/run"
    assert captured["timeout"] == 180.0


def test_parse_sse_messages_returns_event_payloads():
    events = list(
        parse_sse_messages(
            [
                "event: workflow_started",
                'data: {"type":"workflow_started","task_id":"task-1"}',
                "",
                "event: agent_event",
                'data: {"type":"agent_event","event":{"agent":"supervisor"}}',
                "",
            ]
        )
    )

    assert events == [
        {"type": "workflow_started", "task_id": "task-1"},
        {"type": "agent_event", "event": {"agent": "supervisor"}},
    ]


def test_confirm_action_via_api_returns_confirmation_result(monkeypatch):
    captured = {}

    def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(
            {
                "approved": True,
                "status": "approved_pending_executor",
                "action": "browser.open_url",
                "execution": {"status": "not_started"},
            }
        )

    pending_confirmation = {
        "status": "confirmation_required",
        "action": "browser.open_url",
        "plan": {"url": "https://example.com"},
    }
    monkeypatch.setattr("httpx.post", fake_post)

    result = confirm_action_via_api(
        pending_confirmation,
        approved=True,
        api_base_url="http://test",
    )

    assert result["status"] == "approved_pending_executor"
    assert captured == {
        "url": "http://test/api/actions/confirm",
        "json": {
            "pending_confirmation": pending_confirmation,
            "approved": True,
        },
        "timeout": 30.0,
    }


def test_background_job_api_client_submits_and_reads_job(monkeypatch):
    captured = []
    payload = {
        "job_id": "job-1",
        "kind": "chat",
        "label": "研究任务",
        "status": "pending",
        "request": {},
        "progress": {},
        "result": {},
        "error": "",
        "created_at": "2026-07-23T00:00:00+00:00",
        "started_at": None,
        "completed_at": None,
        "updated_at": "2026-07-23T00:00:00+00:00",
    }

    def fake_post(url: str, json=None, timeout: float = 0) -> FakeResponse:
        captured.append(("POST", url, json))
        return FakeResponse(payload)

    def fake_get(url: str, timeout: float = 0) -> FakeResponse:
        captured.append(("GET", url, None))
        return FakeResponse(payload)

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("httpx.get", fake_get)

    submitted = submit_multi_agent_job_via_api(
        "研究 Agent",
        kind="chat",
        label="研究任务",
        api_base_url="http://test",
    )
    loaded = get_background_job_via_api("job-1", api_base_url="http://test")
    brief = run_daily_brief_now_via_api(api_base_url="http://test")

    assert submitted["job_id"] == "job-1"
    assert loaded["status"] == "pending"
    assert brief["job_id"] == "job-1"
    assert captured[0][1] == "http://test/api/background-jobs/multi-agent"
    assert captured[1][1] == "http://test/api/background-jobs/job-1"
    assert captured[2][1] == "http://test/api/daily-brief/run"


def test_daily_brief_schedule_crud_api_client(monkeypatch):
    captured: list[tuple[str, str]] = []
    schedule = {
        "schedule_id": "schedule-1",
        "name": "晨间简报",
        "enabled": True,
        "run_time": "08:00",
        "timezone": "Asia/Shanghai",
        "last_run_date": "",
        "created_at": "",
        "updated_at": "",
    }

    def fake_get(url: str, timeout: float = 0):
        captured.append(("GET", url))
        return FakeResponse([schedule])

    def fake_post(url: str, json=None, timeout: float = 0):
        captured.append(("POST", url))
        return FakeResponse(schedule)

    def fake_put(url: str, json=None, timeout: float = 0):
        captured.append(("PUT", url))
        return FakeResponse({**schedule, **(json or {})})

    def fake_delete(url: str, timeout: float = 0):
        captured.append(("DELETE", url))
        return FakeResponse({"schedule_id": "schedule-1", "status": "deleted"})

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("httpx.put", fake_put)
    monkeypatch.setattr("httpx.delete", fake_delete)

    assert list_daily_brief_schedules_via_api(api_base_url="http://test")[0]["name"] == "晨间简报"
    assert create_daily_brief_schedule_via_api(schedule, api_base_url="http://test")["schedule_id"] == "schedule-1"
    assert update_daily_brief_schedule_by_id_via_api(
        "schedule-1", {"run_time": "09:00"}, api_base_url="http://test"
    )["run_time"] == "09:00"
    assert delete_daily_brief_schedule_via_api(
        "schedule-1", api_base_url="http://test"
    )["status"] == "deleted"
    assert captured == [
        ("GET", "http://test/api/daily-brief/schedules"),
        ("POST", "http://test/api/daily-brief/schedules"),
        ("PUT", "http://test/api/daily-brief/schedules/schedule-1"),
        ("DELETE", "http://test/api/daily-brief/schedules/schedule-1"),
    ]


def test_get_monitor_latest_result_via_api(monkeypatch):
    captured = {}

    def fake_get(url: str, timeout: float = 0) -> FakeResponse:
        captured.update({"url": url, "timeout": timeout})
        return FakeResponse(
            {
                "rule_id": "rule-1",
                "status": "completed",
                "item_count": 1,
                "items": [{"title": "Update", "url": "https://example.com"}],
            }
        )

    monkeypatch.setattr("httpx.get", fake_get)

    result = get_monitor_latest_result_via_api(
        "rule-1",
        api_base_url="http://test",
    )

    assert result["item_count"] == 1
    assert captured["url"] == "http://test/api/monitor/rules/rule-1/latest-result"
