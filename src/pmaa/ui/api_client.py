import json
from collections.abc import Iterable, Iterator

import httpx

from pmaa.config import settings
from pmaa.workflow.state import WorkflowResult


class WorkflowAPIError(RuntimeError):
    pass


def parse_sse_messages(lines: Iterable[str]) -> Iterator[dict]:
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if data_lines:
                yield json.loads("\n".join(data_lines))
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if data_lines:
        yield json.loads("\n".join(data_lines))


def stream_workflow_via_api(
    user_input: str,
    conversation_context: str = "",
    api_base_url: str | None = None,
    timeout: float = 120.0,
) -> Iterator[dict]:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        with httpx.stream(
            "POST",
            f"{base_url}/api/workflows/stream",
            json={
                "user_input": user_input,
                "conversation_context": conversation_context,
            },
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            yield from parse_sse_messages(response.iter_lines())
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"FastAPI 工作流流式接口调用失败：{exc}") from exc


def stream_multi_agent_via_api(
    user_input: str,
    conversation_context: str = "",
    api_base_url: str | None = None,
    timeout: float = 180.0,
) -> Iterator[dict]:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        with httpx.stream(
            "POST",
            f"{base_url}/api/multi-agent/stream",
            json={
                "user_input": user_input,
                "conversation_context": conversation_context,
            },
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            yield from parse_sse_messages(response.iter_lines())
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"FastAPI 多 Agent 流式接口调用失败：{exc}") from exc


def run_workflow_via_api(
    user_input: str,
    conversation_context: str = "",
    api_base_url: str | None = None,
    timeout: float = 120.0,
) -> WorkflowResult:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/workflows/run",
            json={
                "user_input": user_input,
                "conversation_context": conversation_context,
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"FastAPI 工作流接口调用失败：{exc}") from exc

    return WorkflowResult.model_validate(response.json())


def run_multi_agent_via_api(
    user_input: str,
    conversation_context: str = "",
    api_base_url: str | None = None,
    timeout: float = 180.0,
) -> WorkflowResult:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/multi-agent/run",
            json={
                "user_input": user_input,
                "conversation_context": conversation_context,
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"FastAPI 多 Agent 接口调用失败：{exc}") from exc
    return WorkflowResult.model_validate(response.json())


def submit_multi_agent_job_via_api(
    user_input: str,
    conversation_context: str = "",
    *,
    kind: str = "chat",
    label: str = "Agent 任务",
    metadata: dict | None = None,
    api_base_url: str | None = None,
    timeout: float = 15.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/background-jobs/multi-agent",
            json={
                "user_input": user_input,
                "conversation_context": conversation_context,
                "kind": kind,
                "label": label,
                "metadata": metadata or {},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"提交后台 Agent 任务失败：{exc}") from exc


def get_background_job_via_api(
    job_id: str,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(
            f"{base_url}/api/background-jobs/{job_id}",
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取后台任务失败：{exc}") from exc


def list_background_jobs_via_api(
    *,
    kind: str = "",
    limit: int = 20,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> list[dict]:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(
            f"{base_url}/api/background-jobs",
            params={"kind": kind, "limit": limit},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取后台任务列表失败：{exc}") from exc


def get_daily_brief_schedule_via_api(
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/daily-brief/schedule", timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取简报计划失败：{exc}") from exc


def list_daily_brief_schedules_via_api(
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> list[dict]:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/daily-brief/schedules", timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取简报计划列表失败：{exc}") from exc


def create_daily_brief_schedule_via_api(
    payload: dict,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/daily-brief/schedules",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"新增简报计划失败：{exc}") from exc


def update_daily_brief_schedule_by_id_via_api(
    schedule_id: str,
    payload: dict,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.put(
            f"{base_url}/api/daily-brief/schedules/{schedule_id}",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"修改简报计划失败：{exc}") from exc


def delete_daily_brief_schedule_via_api(
    schedule_id: str,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.delete(
            f"{base_url}/api/daily-brief/schedules/{schedule_id}",
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"删除简报计划失败：{exc}") from exc


def update_daily_brief_schedule_via_api(
    payload: dict,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.put(
            f"{base_url}/api/daily-brief/schedule",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"保存简报计划失败：{exc}") from exc


def run_daily_brief_now_via_api(
    schedule_id: str = "",
    api_base_url: str | None = None,
    timeout: float = 15.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        if schedule_id:
            response = httpx.post(
                f"{base_url}/api/daily-brief/run",
                params={"schedule_id": schedule_id},
                timeout=timeout,
            )
        else:
            response = httpx.post(
                f"{base_url}/api/daily-brief/run",
                timeout=timeout,
            )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"启动每日简报失败：{exc}") from exc


def confirm_action_via_api(
    pending_confirmation: dict,
    approved: bool,
    api_base_url: str | None = None,
    timeout: float = 30.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/actions/confirm",
            json={
                "pending_confirmation": pending_confirmation,
                "approved": approved,
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"FastAPI 动作确认接口调用失败：{exc}") from exc
    return response.json()


def list_interest_topics_via_api(
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> list[dict]:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/interest-topics", timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取关注主题失败：{exc}") from exc


def create_interest_topic_via_api(
    payload: dict,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/interest-topics",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"创建关注主题失败：{exc}") from exc


def update_interest_topic_selection_via_api(
    topic_ids: list[str],
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> list[dict]:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.put(
            f"{base_url}/api/interest-topics/selection",
            json={"topic_ids": topic_ids},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"保存关注主题失败：{exc}") from exc


def delete_interest_topic_via_api(
    topic_id: str,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.delete(
            f"{base_url}/api/interest-topics/{topic_id}",
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"删除关注主题失败：{exc}") from exc


def list_monitor_rules_via_api(
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> list[dict]:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/monitor/rules", timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取监控规则失败：{exc}") from exc


def create_monitor_rule_via_api(
    payload: dict,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/monitor/rules",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"创建监控规则失败：{exc}") from exc


def update_monitor_rule_via_api(
    rule_id: str,
    payload: dict,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.patch(
            f"{base_url}/api/monitor/rules/{rule_id}",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"更新监控规则失败：{exc}") from exc


def delete_monitor_rule_via_api(
    rule_id: str,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.delete(
            f"{base_url}/api/monitor/rules/{rule_id}",
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"删除监控规则失败：{exc}") from exc


def run_monitor_rule_via_api(
    rule_id: str,
    api_base_url: str | None = None,
    timeout: float = 15.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/monitor/rules/{rule_id}/run",
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"启动监控任务失败：{exc}") from exc


def get_monitor_latest_result_via_api(
    rule_id: str,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(
            f"{base_url}/api/monitor/rules/{rule_id}/latest-result",
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取监控结果失败：{exc}") from exc


def get_automation_status_via_api(
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/automation/status", timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取调度状态失败：{exc}") from exc


def list_notifications_via_api(
    *,
    unread_only: bool = False,
    limit: int = 50,
    kind: str = "",
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> list[dict]:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(
            f"{base_url}/api/notifications",
            params={"unread_only": unread_only, "limit": limit, "kind": kind or None},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"读取通知失败：{exc}") from exc


def get_notification_unread_count_via_api(
    kind: str = "",
    api_base_url: str | None = None,
    timeout: float = 5.0,
) -> int:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.get(
            f"{base_url}/api/notifications/unread-count",
            params={"kind": kind} if kind else None,
            timeout=timeout,
        )
        response.raise_for_status()
        return int(response.json().get("count", 0))
    except httpx.HTTPError:
        return 0


def mark_notification_read_via_api(
    notification_id: str,
    read: bool = True,
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.patch(
            f"{base_url}/api/notifications/{notification_id}/read",
            json={"read": read},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"更新通知状态失败：{exc}") from exc


def mark_all_notifications_read_via_api(
    kind: str = "",
    api_base_url: str | None = None,
    timeout: float = 10.0,
) -> dict:
    base_url = (api_base_url or settings.api_base_url).rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/api/notifications/mark-all-read",
            params={"kind": kind} if kind else None,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise WorkflowAPIError(f"更新通知状态失败：{exc}") from exc
