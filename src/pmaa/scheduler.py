from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event, RLock, Thread
from typing import Any
from zoneinfo import ZoneInfo

from pmaa.multi_agent.contracts import AgentResult, AgentStatus
from pmaa.schemas.daily_brief import DailyBriefSchedule
from pmaa.schemas.monitor import MonitorRule
from pmaa.schemas.notification import NotificationRecord
from pmaa.storage.monitor_store import SQLiteMonitorStore
from pmaa.storage.notification_store import SQLiteNotificationStore
from pmaa.storage.daily_brief_store import SQLiteDailyBriefScheduleStore


MonitorRunner = Callable[[MonitorRule], AgentResult | dict[str, Any]]
DailyBriefSubmitter = Callable[[DailyBriefSchedule], str]


class SchedulerWorker:
    def __init__(
        self,
        *,
        monitor_store: SQLiteMonitorStore,
        notification_store: SQLiteNotificationStore,
        monitor_runner: MonitorRunner,
        poll_seconds: float = 60.0,
        monitor_scheduling_enabled: bool = True,
        daily_brief_store: SQLiteDailyBriefScheduleStore | None = None,
        daily_brief_submitter: DailyBriefSubmitter | None = None,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive.")
        self.monitor_store = monitor_store
        self.notification_store = notification_store
        self.monitor_runner = monitor_runner
        self.poll_seconds = poll_seconds
        self.monitor_scheduling_enabled = monitor_scheduling_enabled
        self.daily_brief_store = daily_brief_store
        self.daily_brief_submitter = daily_brief_submitter
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = RLock()
        self._last_tick_at: str | None = None
        self._last_error = ""
        self._completed_runs = 0
        self._failed_runs = 0

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run_loop,
                name="pmaa-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def run_once(
        self,
        now: datetime | None = None,
        *,
        include_monitors: bool = True,
    ) -> dict[str, Any]:
        observed_at = self._as_utc(now or datetime.now(UTC))
        due_rules = []
        if include_monitors:
            due_rules = [
                rule
                for rule in self.monitor_store.list_rules(enabled_only=True)
                if self.is_due(rule, observed_at)
            ]
        reports = [self.run_rule(rule, observed_at) for rule in due_rules]
        daily_brief_reports = self.run_daily_briefs_if_due(observed_at)
        self._last_tick_at = observed_at.isoformat()
        return {
            "checked_at": self._last_tick_at,
            "due_count": len(due_rules),
            "completed_count": sum(item["status"] == "completed" for item in reports),
            "failed_count": sum(item["status"] == "failed" for item in reports),
            "reports": reports,
            "daily_brief": daily_brief_reports[0] if daily_brief_reports else None,
            "daily_briefs": daily_brief_reports,
        }

    def run_daily_briefs_if_due(
        self,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if self.daily_brief_store is None or self.daily_brief_submitter is None:
            return []
        observed_at = self._as_utc(now or datetime.now(UTC))
        reports: list[dict[str, Any]] = []
        for schedule in self.daily_brief_store.list_schedules(enabled_only=True):
            local_now = observed_at.astimezone(ZoneInfo(schedule.timezone))
            scheduled_time = datetime.strptime(schedule.run_time, "%H:%M").time()
            local_date = local_now.date().isoformat()
            if local_now.time().replace(second=0, microsecond=0) < scheduled_time:
                continue
            if schedule.last_run_date == local_date:
                continue
            try:
                job_id = self.daily_brief_submitter(schedule)
                self.daily_brief_store.mark_run_date(schedule.schedule_id, local_date)
                reports.append(
                    {
                        "status": "accepted",
                        "job_id": job_id,
                        "schedule_id": schedule.schedule_id,
                        "schedule_name": schedule.name,
                        "local_date": local_date,
                        "run_time": schedule.run_time,
                    }
                )
            except Exception as exc:
                self._last_error = str(exc)
                reports.append(
                    {
                        "status": "failed",
                        "error": str(exc),
                        "schedule_id": schedule.schedule_id,
                        "schedule_name": schedule.name,
                        "local_date": local_date,
                    }
                )
        return reports

    def run_daily_brief_if_due(
        self,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        reports = self.run_daily_briefs_if_due(now)
        return reports[0] if reports else None

    def run_rule(
        self,
        rule: MonitorRule,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = self._as_utc(now or datetime.now(UTC))
        try:
            raw_result = self.monitor_runner(rule)
            result = self._normalize_result(raw_result)
            failed = result.get("status") == AgentStatus.FAILED.value
            if failed:
                raise RuntimeError("; ".join(result.get("errors", [])) or "Monitor agent failed.")
            notification_ids = self._publish_monitor_notifications(rule, result)
            self.monitor_store.mark_run(rule.rule_id, observed_at.isoformat())
            self._completed_runs += 1
            self._last_error = ""
            return {
                "rule_id": rule.rule_id,
                "status": "completed",
                "change_count": len(result.get("important_changes", [])),
                "baseline_created": int(result.get("baseline_created", 0) or 0),
                "notification_ids": notification_ids,
            }
        except Exception as exc:
            self.monitor_store.mark_run(rule.rule_id, observed_at.isoformat())
            notification = self.notification_store.save(
                NotificationRecord(
                    kind="system",
                    title=f"监控任务失败：{rule.name}",
                    content=str(exc),
                    severity="warning",
                    source_agent="information_monitor",
                    related_rule_id=rule.rule_id,
                    metadata={"target": rule.target, "query": rule.query},
                )
            )
            self._failed_runs += 1
            self._last_error = str(exc)
            return {
                "rule_id": rule.rule_id,
                "status": "failed",
                "error": str(exc),
                "notification_ids": [notification.notification_id],
            }

    def status(self) -> dict[str, Any]:
        thread = self._thread
        daily_schedules = (
            self.daily_brief_store.list_schedules() if self.daily_brief_store else []
        )
        enabled_daily_schedules = [item for item in daily_schedules if item.enabled]
        return {
            "running": bool(thread and thread.is_alive()),
            "poll_seconds": self.poll_seconds,
            "last_tick_at": self._last_tick_at,
            "last_error": self._last_error,
            "completed_runs": self._completed_runs,
            "failed_runs": self._failed_runs,
            "enabled_rule_count": len(self.monitor_store.list_rules(enabled_only=True)),
            "daily_brief_enabled": bool(enabled_daily_schedules),
            "daily_brief_schedule_count": len(daily_schedules),
            "daily_brief_enabled_count": len(enabled_daily_schedules),
            "daily_brief_times": [item.run_time for item in enabled_daily_schedules],
        }

    @staticmethod
    def is_due(rule: MonitorRule, now: datetime) -> bool:
        if not rule.enabled:
            return False
        if not rule.last_run_at:
            return True
        try:
            last_run = datetime.fromisoformat(rule.last_run_at)
        except ValueError:
            return True
        last_run = SchedulerWorker._as_utc(last_run)
        return now >= last_run + timedelta(minutes=rule.interval_minutes)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once(include_monitors=self.monitor_scheduling_enabled)
            except Exception as exc:  # The worker must survive one bad tick.
                self._last_error = str(exc)
            self._stop_event.wait(self.poll_seconds)

    def _publish_monitor_notifications(
        self,
        rule: MonitorRule,
        result: dict[str, Any],
    ) -> list[str]:
        important_changes = result.get("important_changes", [])
        if not isinstance(important_changes, list) or not important_changes:
            return []
        lines: list[str] = []
        for item in important_changes:
            if not isinstance(item, dict):
                lines.append(f"- {item}")
                continue
            change = item.get("change", {})
            if isinstance(change, dict):
                title = str(change.get("title") or change.get("url") or "监控更新")
                url = str(change.get("url") or "")
                label = f"[{title}]({url})" if url else title
            else:
                label = str(change)
            relevance = str(item.get("relevance") or "").strip()
            action = str(item.get("recommended_action") or "").strip()
            detail = "；".join(value for value in (relevance, action) if value)
            lines.append(f"- {label}" + (f"：{detail}" if detail else ""))
        notification = self.notification_store.save(
            NotificationRecord(
                kind="monitor",
                title=f"{rule.name} 有 {len(important_changes)} 条重要变化",
                content="\n".join(lines),
                severity="info",
                source_agent="information_monitor",
                related_rule_id=rule.rule_id,
                metadata={
                    "target_type": rule.target_type,
                    "target": rule.target,
                    "change_count": len(important_changes),
                },
            )
        )
        return [notification.notification_id]

    @staticmethod
    def _normalize_result(result: AgentResult | dict[str, Any]) -> dict[str, Any]:
        if isinstance(result, AgentResult):
            return {
                "status": result.status.value,
                "errors": result.errors,
                **result.output,
            }
        payload = dict(result)
        status = payload.get("status")
        if isinstance(status, AgentStatus):
            payload["status"] = status.value
        return payload

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
