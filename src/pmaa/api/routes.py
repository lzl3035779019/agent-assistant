import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from pmaa.schemas.task import Task, TaskStatus
from pmaa.skills.confirmation import confirm_pending_action
from pmaa.skills.executors import create_default_executor_registry
from pmaa.storage.task_store import task_store
from pmaa.workflow.graph import run_workflow, stream_workflow_events
from pmaa.workflow.state import WorkflowResult


router = APIRouter(prefix="/api")


class CreateTaskRequest(BaseModel):
    user_input: str


class RunWorkflowRequest(BaseModel):
    user_input: str
    conversation_context: str = ""


class ConfirmActionRequest(BaseModel):
    pending_confirmation: dict[str, Any]
    approved: bool


@router.post("/workflows/run", response_model=WorkflowResult)
def run_workflow_endpoint(request: RunWorkflowRequest) -> WorkflowResult:
    return run_workflow(
        request.user_input,
        use_configured_llm=True,
        use_configured_search=True,
        conversation_context=request.conversation_context,
        enable_memory=True,
        enable_skills=True,
    )


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


def format_sse_message(event: dict[str, Any]) -> str:
    event_name = event["type"]
    payload = _to_jsonable(event)
    return (
        f"event: {event_name}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


@router.post("/workflows/stream")
def stream_workflow_endpoint(request: RunWorkflowRequest) -> StreamingResponse:
    def event_generator():
        try:
            for event in stream_workflow_events(
                request.user_input,
                use_configured_llm=True,
                use_configured_search=True,
                conversation_context=request.conversation_context,
                enable_memory=True,
                enable_skills=True,
            ):
                yield format_sse_message(event)
        except Exception as exc:
            yield format_sse_message(
                {
                    "type": "workflow_error",
                    "error": str(exc),
                }
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/actions/confirm")
def confirm_action_endpoint(request: ConfirmActionRequest) -> dict[str, Any]:
    return confirm_pending_action(
        request.pending_confirmation,
        approved=request.approved,
        executor_registry=create_default_executor_registry(),
    )


@router.post("/tasks", response_model=Task)
def create_task(request: CreateTaskRequest) -> Task:
    task = Task(user_input=request.user_input, status=TaskStatus.RUNNING)
    workflow_result = run_workflow(request.user_input)
    task.result = workflow_result.final_result
    task.status = TaskStatus.COMPLETED
    return task_store.save(task)


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: str) -> Task:
    task = task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
