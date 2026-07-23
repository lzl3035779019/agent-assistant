from __future__ import annotations

import time
from datetime import UTC, datetime

from pmaa.background_jobs import BackgroundJobManager
from pmaa.schemas.background_job import BackgroundJob, BackgroundJobStatus
from pmaa.schemas.daily_brief import DailyBriefSchedule
from pmaa.schemas.monitor import MonitorRule
from pmaa.scheduler import SchedulerWorker
from pmaa.storage.background_job_store import SQLiteBackgroundJobStore
from pmaa.storage.daily_brief_store import SQLiteDailyBriefScheduleStore
from pmaa.storage.monitor_store import SQLiteMonitorStore
from pmaa.storage.notification_store import SQLiteNotificationStore


def completed_workflow_stream(user_input: str, conversation_context: str):
    yield {
        "type": "agent_event",
        "event": {
            "task_id": "task-1",
            "agent": "supervisor",
            "event_type": "decision_completed",
            "input": {},
            "output": {"intent": "direct_answer"},
            "timestamp": "2026-07-23T00:00:00+00:00",
        },
    }
    yield {
        "type": "workflow_completed",
        "result": {
            "task_id": "task-1",
            "user_input": user_input,
            "conversation_context": conversation_context,
            "final_result": {
                "answer": "后台任务已完成。",
                "sources": [],
                "reflection": {
                    "passed": True,
                    "issues": [],
                    "suggested_fix": "",
                    "need_retry": False,
                },
            },
            "events": [],
        },
    }


def wait_for_terminal_job(store: SQLiteBackgroundJobStore, job_id: str) -> BackgroundJob:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = store.get(job_id)
        assert job is not None
        if job.status in {BackgroundJobStatus.COMPLETED, BackgroundJobStatus.FAILED}:
            return job
        time.sleep(0.02)
    raise AssertionError("Background job did not finish in time")


def test_background_job_runs_outside_request_and_persists_progress(tmp_path) -> None:
    store = SQLiteBackgroundJobStore(tmp_path / "jobs.sqlite3")
    completed: list[str] = []
    manager = BackgroundJobManager(
        store=store,
        workflow_stream=completed_workflow_stream,
        on_completed=lambda job: completed.append(job.job_id),
    )

    submitted = manager.submit_multi_agent(
        user_input="生成简报",
        kind="daily_brief",
        label="今日简报",
    )
    terminal = wait_for_terminal_job(store, submitted.job_id)
    manager.shutdown(wait=True)

    assert terminal.status == BackgroundJobStatus.COMPLETED
    assert terminal.result["final_result"]["answer"] == "后台任务已完成。"
    assert terminal.progress["events"][0]["agent"] == "supervisor"
    assert completed == [submitted.job_id]


def test_background_job_forwards_explicit_agent_assignment(tmp_path) -> None:
    store = SQLiteBackgroundJobStore(tmp_path / "jobs.sqlite3")
    captured: list[str] = []

    def assigned_stream(
        user_input: str,
        conversation_context: str,
        assigned_agent: str = "",
    ):
        captured.append(assigned_agent)
        yield from completed_workflow_stream(user_input, conversation_context)

    manager = BackgroundJobManager(store=store, workflow_stream=assigned_stream)
    submitted = manager.submit_multi_agent(
        user_input="生成今日简报",
        kind="daily_brief",
        assigned_agent="daily_brief",
    )
    terminal = wait_for_terminal_job(store, submitted.job_id)
    manager.shutdown(wait=True)

    assert terminal.status == BackgroundJobStatus.COMPLETED
    assert terminal.request["assigned_agent"] == "daily_brief"
    assert captured == ["daily_brief"]


def test_background_job_store_marks_interrupted_jobs_failed(tmp_path) -> None:
    path = tmp_path / "jobs.sqlite3"
    store = SQLiteBackgroundJobStore(path)
    running = store.save(
        BackgroundJob(
            kind="chat",
            label="测试任务",
            status=BackgroundJobStatus.RUNNING,
        )
    )

    recovered_store = SQLiteBackgroundJobStore(path)
    recovered_store.recover_interrupted_jobs()
    recovered = recovered_store.get(running.job_id)

    assert recovered is not None
    assert recovered.status == BackgroundJobStatus.FAILED
    assert "服务重启" in recovered.error


def test_scheduler_submits_daily_brief_once_per_local_day(tmp_path) -> None:
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    notification_store = SQLiteNotificationStore(tmp_path / "notification.sqlite3")
    schedule_store = SQLiteDailyBriefScheduleStore(tmp_path / "automation.sqlite3")
    schedule_store.save(
        DailyBriefSchedule(
            enabled=True,
            run_time="08:00",
            timezone="Asia/Shanghai",
        )
    )
    submitted: list[str] = []
    worker = SchedulerWorker(
        monitor_store=monitor_store,
        notification_store=notification_store,
        monitor_runner=lambda rule: {},
        daily_brief_store=schedule_store,
        daily_brief_submitter=lambda schedule: submitted.append(schedule.name) or "job-1",
    )

    first = worker.run_once(datetime(2026, 7, 23, 0, 5, tzinfo=UTC))
    second = worker.run_once(datetime(2026, 7, 23, 5, 0, tzinfo=UTC))

    assert first["daily_brief"]["status"] == "accepted"
    assert second["daily_brief"] is None
    assert submitted == ["每日简报"]
    assert schedule_store.get().last_run_date == "2026-07-23"


def test_scheduler_can_run_daily_brief_without_monitor_automation(tmp_path) -> None:
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    notification_store = SQLiteNotificationStore(tmp_path / "notification.sqlite3")
    schedule_store = SQLiteDailyBriefScheduleStore(tmp_path / "automation.sqlite3")
    schedule_store.save(
        DailyBriefSchedule(
            enabled=True,
            run_time="08:00",
            timezone="Asia/Shanghai",
        )
    )
    monitor_store.save_rule(
        MonitorRule(
            name="不应自动运行",
            target_type="news",
            target="AI",
            query="AI 新闻",
        )
    )
    monitor_calls: list[str] = []
    brief_calls: list[str] = []
    worker = SchedulerWorker(
        monitor_store=monitor_store,
        notification_store=notification_store,
        monitor_runner=lambda rule: monitor_calls.append(rule.rule_id) or {},
        monitor_scheduling_enabled=False,
        daily_brief_store=schedule_store,
        daily_brief_submitter=lambda schedule: brief_calls.append(schedule.name) or "brief-job",
    )

    report = worker.run_once(
        datetime(2026, 7, 23, 0, 5, tzinfo=UTC),
        include_monitors=False,
    )

    assert report["due_count"] == 0
    assert monitor_calls == []
    assert brief_calls == ["每日简报"]


def test_scheduler_submits_multiple_daily_briefs_on_same_day(tmp_path) -> None:
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    notification_store = SQLiteNotificationStore(tmp_path / "notification.sqlite3")
    schedule_store = SQLiteDailyBriefScheduleStore(tmp_path / "automation.sqlite3")
    morning = schedule_store.save(
        DailyBriefSchedule(name="晨间简报", enabled=True, run_time="08:00")
    )
    noon = schedule_store.save(
        DailyBriefSchedule(name="午间简报", enabled=True, run_time="12:00")
    )
    submitted: list[str] = []
    worker = SchedulerWorker(
        monitor_store=monitor_store,
        notification_store=notification_store,
        monitor_runner=lambda rule: {},
        daily_brief_store=schedule_store,
        daily_brief_submitter=lambda schedule: submitted.append(schedule.name) or schedule.schedule_id,
    )

    first = worker.run_once(datetime(2026, 7, 23, 0, 5, tzinfo=UTC))
    second = worker.run_once(datetime(2026, 7, 23, 4, 5, tzinfo=UTC))

    assert [item["schedule_id"] for item in first["daily_briefs"]] == [
        morning.schedule_id
    ]
    assert [item["schedule_id"] for item in second["daily_briefs"]] == [
        noon.schedule_id
    ]
    assert submitted == ["晨间简报", "午间简报"]


def test_daily_brief_schedule_store_supports_crud(tmp_path) -> None:
    store = SQLiteDailyBriefScheduleStore(tmp_path / "automation.sqlite3")
    morning = store.save(
        DailyBriefSchedule(name="晨间简报", enabled=True, run_time="08:00")
    )
    evening = store.save(
        DailyBriefSchedule(name="晚间简报", enabled=False, run_time="20:00")
    )

    assert [item.name for item in store.list_schedules()] == ["晨间简报", "晚间简报"]
    updated = store.save(evening.model_copy(update={"enabled": True, "run_time": "21:00"}))
    assert store.get(updated.schedule_id).run_time == "21:00"
    assert store.has_enabled() is True
    assert store.delete(morning.schedule_id) is True
    assert [item.schedule_id for item in store.list_schedules()] == [evening.schedule_id]
