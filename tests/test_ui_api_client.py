import httpx
import pytest

from pmaa.ui.api_client import (
    WorkflowAPIError,
    confirm_action_via_api,
    parse_sse_messages,
    run_workflow_via_api,
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
