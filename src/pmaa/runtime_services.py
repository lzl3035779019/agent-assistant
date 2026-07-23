from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from pmaa.config import settings
from pmaa.background_jobs import BackgroundJobManager
from pmaa.multi_agent.contracts import AgentResult
from pmaa.multi_agent.orchestrator import (
    create_default_orchestrator,
    stream_multi_agent_workflow_events,
)
from pmaa.schemas.background_job import BackgroundJob
from pmaa.schemas.daily_brief import DailyBriefSchedule
from pmaa.schemas.monitor import MonitorRule
from pmaa.schemas.notification import NotificationRecord
from pmaa.scheduler import SchedulerWorker
from pmaa.storage.monitor_store import SQLiteMonitorStore
from pmaa.storage.notification_store import SQLiteNotificationStore
from pmaa.storage.interest_topic_store import SQLiteInterestTopicStore
from pmaa.storage.background_job_store import SQLiteBackgroundJobStore
from pmaa.storage.daily_brief_store import SQLiteDailyBriefScheduleStore
from pmaa.workflow.state import WorkflowResult


monitor_store = SQLiteMonitorStore()
notification_store = SQLiteNotificationStore()
interest_topic_store = SQLiteInterestTopicStore()
background_job_store = SQLiteBackgroundJobStore()
daily_brief_schedule_store = SQLiteDailyBriefScheduleStore(
    default_enabled=settings.daily_brief_schedule_enabled,
    default_run_time=settings.daily_brief_schedule_time,
    default_timezone=settings.calendar_timezone,
)


DAILY_BRIEF_OBJECTIVE = (
    "请根据我当天未读和重要邮件、关注主题新闻、今日日程和长期偏好，"
    "生成今日个人简报。"
)


def _on_background_job_completed(job: BackgroundJob) -> None:
    if job.kind != "daily_brief":
        return
    result = WorkflowResult.model_validate(job.result)
    answer = result.final_result.answer if result.final_result else "今日简报已生成。"
    metadata = dict(job.request.get("metadata") or {})
    schedule_name = str(metadata.get("schedule_name") or "今日个人简报")
    notification_store.save(
        NotificationRecord(
            kind="daily_brief",
            title=f"{schedule_name}已生成",
            content=answer[:500],
            severity="info",
            source_agent="daily_brief",
            metadata={"job_id": job.job_id, **metadata},
        )
    )


background_job_manager = BackgroundJobManager(
    store=background_job_store,
    workflow_stream=stream_multi_agent_workflow_events,
    on_completed=_on_background_job_completed,
)


def submit_daily_brief_job(
    *,
    trigger: str = "manual",
    schedule: DailyBriefSchedule | None = None,
) -> BackgroundJob:
    schedule_name = schedule.name if schedule else "今日个人简报"
    objective = f"请生成{schedule_name}。{DAILY_BRIEF_OBJECTIVE}"
    metadata = {
        "trigger": trigger,
        "schedule_id": schedule.schedule_id if schedule else "",
        "schedule_name": schedule_name,
        "run_time": schedule.run_time if schedule else "",
    }
    return background_job_manager.submit_multi_agent(
        user_input=objective,
        kind="daily_brief",
        label=schedule_name,
        metadata=metadata,
        assigned_agent="daily_brief",
    )


def _submit_scheduled_daily_brief(schedule: DailyBriefSchedule) -> str:
    return submit_daily_brief_job(trigger="schedule", schedule=schedule).job_id


def legacy_interest_topic_rule_id(topic_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"pmaa:interest-topic:{topic_id}"))


def remove_legacy_interest_topic_monitor_rules(
    *,
    topic_store: SQLiteInterestTopicStore | None = None,
    rule_store: SQLiteMonitorStore | None = None,
) -> list[str]:
    """Remove only monitor rules created by the former topic-sync behavior."""
    active_topic_store = topic_store or interest_topic_store
    active_rule_store = rule_store or monitor_store
    deleted_rule_ids: list[str] = []
    for topic in active_topic_store.list_topics():
        rule_id = legacy_interest_topic_rule_id(topic.topic_id)
        if active_rule_store.delete_rule(rule_id):
            deleted_rule_ids.append(rule_id)
    return deleted_rule_ids


def run_monitor_rule(rule: MonitorRule) -> AgentResult:
    orchestrator = create_default_orchestrator(
        monitor_store=monitor_store,
        interest_topic_store=interest_topic_store,
    )
    results = orchestrator.run_system_agent_task(
        agent_id="information_monitor",
        objective=f"检查监控规则：{rule.name}",
        context={"rules": [rule.model_dump(mode="json")]},
    )
    parent_results = [
        result
        for result in results.values()
        if result.agent_id == "information_monitor"
    ]
    if not parent_results:
        raise RuntimeError("Information Monitor Agent did not return a result.")
    return parent_results[-1]


def run_monitor_rule_with_feedback(
    rule: MonitorRule,
    *,
    worker: SchedulerWorker | None = None,
    notifications: SQLiteNotificationStore | None = None,
) -> dict:
    active_worker = worker or scheduler_worker
    active_notifications = notifications or notification_store
    report = active_worker.run_rule(rule)
    if report.get("status") != "completed" or report.get("notification_ids"):
        return report

    baseline_created = int(report.get("baseline_created", 0) or 0)
    if baseline_created:
        title = f"{rule.name} 首次检查完成"
        content = "已建立对比基线。后续检查发现重要变化时会继续提醒。"
    else:
        title = f"{rule.name} 检查完成"
        content = "本轮未发现需要提醒的重要变化。"
    notification = active_notifications.save(
        NotificationRecord(
            kind="monitor",
            title=title,
            content=content,
            severity="info",
            source_agent="information_monitor",
            related_rule_id=rule.rule_id,
            metadata={
                "target_type": rule.target_type,
                "target": rule.target,
                "baseline_created": baseline_created,
                "manual_run": True,
            },
        )
    )
    return {
        **report,
        "notification_ids": [notification.notification_id],
    }


remove_legacy_interest_topic_monitor_rules()


scheduler_worker = SchedulerWorker(
    monitor_store=monitor_store,
    notification_store=notification_store,
    monitor_runner=run_monitor_rule,
    poll_seconds=settings.automation_poll_seconds,
    monitor_scheduling_enabled=settings.automation_scheduler_enabled,
    daily_brief_store=daily_brief_schedule_store,
    daily_brief_submitter=_submit_scheduled_daily_brief,
)
