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
