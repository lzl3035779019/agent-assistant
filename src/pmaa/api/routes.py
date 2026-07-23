import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from pmaa.config import settings
from pmaa.schemas.task import Task, TaskStatus
from pmaa.schemas.monitor import MonitorRule, MonitorTargetType
from pmaa.schemas.notification import NotificationKind, NotificationRecord
from pmaa.schemas.interest_topic import InterestTopic
from pmaa.schemas.background_job import BackgroundJob
from pmaa.schemas.daily_brief import (
    DailyBriefSchedule,
    DailyBriefScheduleCreate,
    DailyBriefScheduleUpdate,
)
from pmaa.multi_agent.orchestrator import (
    run_multi_agent_workflow,
    stream_multi_agent_workflow_events,
)
from pmaa.skills.confirmation import confirm_pending_action
from pmaa.skills.executors import create_default_executor_registry
from pmaa.storage.task_store import task_store
from pmaa.runtime_services import (
    background_job_manager,
    background_job_store,
    daily_brief_schedule_store,
    interest_topic_store,
    monitor_store,
    notification_store,
    run_monitor_rule_with_feedback,
    scheduler_worker,
    submit_daily_brief_job,
)
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


class MonitorRuleCreateRequest(BaseModel):
    name: str
    target_type: MonitorTargetType
    target: str
    query: str
    enabled: bool = True
    interval_minutes: int = Field(default=360, ge=15, le=10080)


class MonitorRuleUpdateRequest(BaseModel):
    name: str | None = None
    target_type: MonitorTargetType | None = None
    target: str | None = None
    query: str | None = None
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=15, le=10080)


class NotificationReadRequest(BaseModel):
    read: bool = True


class InterestTopicCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=500)


class InterestTopicSelectionRequest(BaseModel):
    topic_ids: list[str] = Field(default_factory=list)


class BackgroundJobCreateRequest(BaseModel):
    user_input: str = Field(min_length=1)
    conversation_context: str = ""
    kind: str = Field(default="chat", min_length=1, max_length=40)
    label: str = Field(default="Agent 任务", min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


@router.post("/multi-agent/run", response_model=WorkflowResult)
def run_multi_agent_endpoint(request: RunWorkflowRequest) -> WorkflowResult:
    return run_multi_agent_workflow(
        request.user_input,
        conversation_context=request.conversation_context,
    )


@router.post("/background-jobs/multi-agent", response_model=BackgroundJob)
def submit_multi_agent_background_job(
    request: BackgroundJobCreateRequest,
) -> BackgroundJob:
    return background_job_manager.submit_multi_agent(
        user_input=request.user_input.strip(),
        conversation_context=request.conversation_context,
        kind=request.kind,
        label=request.label,
        metadata=request.metadata,
    )


@router.get("/background-jobs", response_model=list[BackgroundJob])
def list_background_jobs(kind: str = "", limit: int = 20) -> list[BackgroundJob]:
    return background_job_store.list_jobs(kind=kind.strip(), limit=limit)


@router.get("/background-jobs/{job_id}", response_model=BackgroundJob)
def get_background_job(job_id: str) -> BackgroundJob:
    job = background_job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Background job not found")
    return job


@router.get("/daily-brief/schedule", response_model=DailyBriefSchedule)
def get_daily_brief_schedule() -> DailyBriefSchedule:
    return daily_brief_schedule_store.get()


@router.put("/daily-brief/schedule", response_model=DailyBriefSchedule)
def update_daily_brief_schedule(
    request: DailyBriefScheduleUpdate,
) -> DailyBriefSchedule:
    current = daily_brief_schedule_store.get()
    saved = daily_brief_schedule_store.save(
        current.model_copy(update=request.model_dump(exclude_none=True))
    )
    if saved.enabled:
        scheduler_worker.start()
    return saved


@router.get("/daily-brief/schedules", response_model=list[DailyBriefSchedule])
def list_daily_brief_schedules() -> list[DailyBriefSchedule]:
    return daily_brief_schedule_store.list_schedules()


@router.post("/daily-brief/schedules", response_model=DailyBriefSchedule)
def create_daily_brief_schedule(
    request: DailyBriefScheduleCreate,
) -> DailyBriefSchedule:
    saved = daily_brief_schedule_store.save(DailyBriefSchedule(**request.model_dump()))
    if saved.enabled:
        scheduler_worker.start()
    return saved


@router.put(
    "/daily-brief/schedules/{schedule_id}",
    response_model=DailyBriefSchedule,
)
def update_daily_brief_schedule_by_id(
    schedule_id: str,
    request: DailyBriefScheduleUpdate,
) -> DailyBriefSchedule:
    try:
        current = daily_brief_schedule_store.get(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Daily brief schedule not found") from exc
    saved = daily_brief_schedule_store.save(
        current.model_copy(update=request.model_dump(exclude_none=True))
    )
    if saved.enabled:
        scheduler_worker.start()
    return saved


@router.delete("/daily-brief/schedules/{schedule_id}")
def delete_daily_brief_schedule(schedule_id: str) -> dict[str, str]:
    if not daily_brief_schedule_store.delete(schedule_id):
        raise HTTPException(status_code=404, detail="Daily brief schedule not found")
    return {"schedule_id": schedule_id, "status": "deleted"}


@router.post("/daily-brief/run", response_model=BackgroundJob)
def run_daily_brief_now(schedule_id: str = "") -> BackgroundJob:
    schedule = None
    if schedule_id.strip():
        try:
            schedule = daily_brief_schedule_store.get(schedule_id.strip())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Daily brief schedule not found") from exc
    return submit_daily_brief_job(trigger="manual", schedule=schedule)


@router.post("/multi-agent/stream")
def stream_multi_agent_endpoint(request: RunWorkflowRequest) -> StreamingResponse:
    def event_generator():
        try:
            for event in stream_multi_agent_workflow_events(
                request.user_input,
                conversation_context=request.conversation_context,
            ):
                yield format_sse_message(event)
        except Exception as exc:
            yield format_sse_message(
                {
                    "type": "workflow_error",
                    "error": str(exc),
                    "architecture": "hierarchical_multi_agent",
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


@router.get("/interest-topics", response_model=list[InterestTopic])
def list_interest_topics(enabled_only: bool = False) -> list[InterestTopic]:
    return interest_topic_store.list_topics(enabled_only=enabled_only)


@router.post("/interest-topics", response_model=InterestTopic)
def create_interest_topic(request: InterestTopicCreateRequest) -> InterestTopic:
    name = request.name.strip()
    query = request.query.strip()
    if not name or not query:
        raise HTTPException(status_code=422, detail="Topic name and query are required")
    duplicate = next(
        (
            topic
            for topic in interest_topic_store.list_topics()
            if topic.name.casefold() == name.casefold()
        ),
        None,
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Interest topic already exists")
    return interest_topic_store.save_topic(InterestTopic(name=name, query=query))


@router.put("/interest-topics/selection", response_model=list[InterestTopic])
def update_interest_topic_selection(
    request: InterestTopicSelectionRequest,
) -> list[InterestTopic]:
    try:
        topics = interest_topic_store.set_enabled_topics(request.topic_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return topics


@router.delete("/interest-topics/{topic_id}")
def delete_interest_topic(topic_id: str) -> dict[str, Any]:
    try:
        deleted = interest_topic_store.delete_topic(topic_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Interest topic not found")
    return {"deleted": True, "topic_id": topic_id}


@router.get("/monitor/rules", response_model=list[MonitorRule])
def list_monitor_rules(enabled_only: bool = False) -> list[MonitorRule]:
    return monitor_store.list_rules(enabled_only=enabled_only)


@router.post("/monitor/rules", response_model=MonitorRule)
def create_monitor_rule(request: MonitorRuleCreateRequest) -> MonitorRule:
    return monitor_store.save_rule(MonitorRule(**request.model_dump()))


@router.patch("/monitor/rules/{rule_id}", response_model=MonitorRule)
def update_monitor_rule(
    rule_id: str,
    request: MonitorRuleUpdateRequest,
) -> MonitorRule:
    current = monitor_store.get_rule(rule_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Monitor rule not found")
    payload = current.model_dump()
    payload.update(request.model_dump(exclude_none=True))
    return monitor_store.save_rule(MonitorRule.model_validate(payload))


@router.delete("/monitor/rules/{rule_id}")
def delete_monitor_rule(rule_id: str) -> dict[str, Any]:
    if not monitor_store.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Monitor rule not found")
    return {"deleted": True, "rule_id": rule_id}


@router.post("/monitor/rules/{rule_id}/run")
def run_monitor_rule_now(
    rule_id: str,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    rule = monitor_store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Monitor rule not found")
    background_tasks.add_task(run_monitor_rule_with_feedback, rule)
    return {"rule_id": rule_id, "status": "accepted"}


@router.get("/monitor/rules/{rule_id}/latest-result")
def get_monitor_rule_latest_result(rule_id: str) -> dict[str, Any]:
    rule = monitor_store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Monitor rule not found")
    snapshot = monitor_store.latest_snapshot(rule_id)
    return {
        "rule_id": rule_id,
        "rule_name": rule.name,
        "last_run_at": rule.last_run_at,
        "status": "completed" if rule.last_run_at else "not_run",
        "snapshot_id": snapshot.snapshot_id if snapshot else None,
        "observed_at": snapshot.observed_at if snapshot else None,
        "item_count": len(snapshot.items) if snapshot else 0,
        "items": snapshot.items if snapshot else [],
    }


@router.get("/automation/status")
def get_automation_status() -> dict[str, Any]:
    return {
        **scheduler_worker.status(),
        "configured_enabled": settings.automation_scheduler_enabled,
        "github_token_configured": bool(settings.github_token),
    }


@router.post("/automation/run-once")
def run_automation_once() -> dict[str, Any]:
    return scheduler_worker.run_once()


@router.get("/notifications", response_model=list[NotificationRecord])
def list_notifications(
    limit: int = 50,
    unread_only: bool = False,
    kind: NotificationKind | None = None,
) -> list[NotificationRecord]:
    return notification_store.list_notifications(
        limit=limit,
        unread_only=unread_only,
        kind=kind,
    )


@router.get("/notifications/unread-count")
def get_notification_unread_count(
    kind: NotificationKind | None = None,
) -> dict[str, int]:
    return {"count": notification_store.count_unread(kind=kind)}


@router.patch("/notifications/{notification_id}/read")
def update_notification_read(
    notification_id: str,
    request: NotificationReadRequest,
) -> dict[str, Any]:
    if not notification_store.mark_read(notification_id, request.read):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"notification_id": notification_id, "read": request.read}


@router.post("/notifications/mark-all-read")
def mark_all_notifications_read(
    kind: NotificationKind | None = None,
) -> dict[str, int]:
    return {"updated": notification_store.mark_all_read(kind=kind)}


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
