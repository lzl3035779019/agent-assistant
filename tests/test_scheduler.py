from datetime import UTC, datetime, timedelta

from pmaa.multi_agent.contracts import AgentResult, AgentStatus
from pmaa.schemas.monitor import MonitorRule
from pmaa.scheduler import SchedulerWorker
from pmaa.runtime_services import run_monitor_rule_with_feedback
from pmaa.storage.monitor_store import SQLiteMonitorStore
from pmaa.storage.notification_store import SQLiteNotificationStore


def test_scheduler_runs_only_due_rules_and_creates_change_notification(tmp_path) -> None:
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    notification_store = SQLiteNotificationStore(tmp_path / "notifications.sqlite3")
    rule = monitor_store.save_rule(
        MonitorRule(
            name="Vercel jobs",
            target_type="jobs",
            target="Vercel",
            query="Vercel AI jobs",
            interval_minutes=60,
        )
    )
    calls: list[str] = []

    def runner(current: MonitorRule) -> AgentResult:
        calls.append(current.rule_id)
        return AgentResult(
            task_id="monitor-task",
            agent_id="information_monitor",
            status=AgentStatus.COMPLETED,
            output={
                "important_changes": [
                    {
                        "change": {
                            "title": "AI Engineer",
                            "url": "https://vercel.com/jobs/ai",
                        },
                        "relevance": "匹配用户目标",
                        "recommended_action": "查看岗位",
                    }
                ]
            },
        )

    worker = SchedulerWorker(
        monitor_store=monitor_store,
        notification_store=notification_store,
        monitor_runner=runner,
        poll_seconds=10,
    )
    now = datetime(2026, 7, 23, 8, tzinfo=UTC)

    first = worker.run_once(now)
    second = worker.run_once(now + timedelta(minutes=30))

    assert first["due_count"] == 1
    assert second["due_count"] == 0
    assert calls == [rule.rule_id]
    assert notification_store.count_unread() == 1
    notification = notification_store.list_notifications()[0]
    assert notification.related_rule_id == rule.rule_id
    assert "AI Engineer" in notification.content


def test_scheduler_isolates_rule_failure_and_emits_warning(tmp_path) -> None:
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    notification_store = SQLiteNotificationStore(tmp_path / "notifications.sqlite3")
    rule = monitor_store.save_rule(
        MonitorRule(
            name="Broken monitor",
            target_type="news",
            target="Example",
            query="Example news",
        )
    )

    def runner(_rule: MonitorRule):
        raise RuntimeError("search unavailable")

    worker = SchedulerWorker(
        monitor_store=monitor_store,
        notification_store=notification_store,
        monitor_runner=runner,
    )

    report = worker.run_rule(rule)

    assert report["status"] == "failed"
    notification = notification_store.list_notifications()[0]
    assert notification.severity == "warning"
    assert "search unavailable" in notification.content


def test_manual_monitor_run_publishes_baseline_feedback(tmp_path) -> None:
    monitor_store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    notification_store = SQLiteNotificationStore(tmp_path / "notifications.sqlite3")
    rule = monitor_store.save_rule(
        MonitorRule(
            name="主题：AI 与大模型",
            target_type="news",
            target="AI 与大模型",
            query="今天 AI 大模型的重要动态",
        )
    )

    def runner(_rule: MonitorRule) -> AgentResult:
        return AgentResult(
            task_id="monitor-task",
            agent_id="information_monitor",
            status=AgentStatus.COMPLETED,
            output={"important_changes": [], "baseline_created": 1},
        )

    worker = SchedulerWorker(
        monitor_store=monitor_store,
        notification_store=notification_store,
        monitor_runner=runner,
    )

    report = run_monitor_rule_with_feedback(
        rule,
        worker=worker,
        notifications=notification_store,
    )

    assert report["status"] == "completed"
    assert len(report["notification_ids"]) == 1
    notification = notification_store.list_notifications()[0]
    assert "首次检查完成" in notification.title
    assert "建立对比基线" in notification.content
