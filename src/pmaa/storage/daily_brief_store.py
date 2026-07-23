from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pmaa.schemas.daily_brief import DailyBriefSchedule


class SQLiteDailyBriefScheduleStore:
    def __init__(
        self,
        db_path: str | Path = "data/pmaa_automation.sqlite3",
        *,
        default_enabled: bool = False,
        default_run_time: str = "08:00",
        default_timezone: str = "Asia/Shanghai",
    ) -> None:
        self._db_path = Path(db_path)
        self._default_schedule = DailyBriefSchedule(
            name="每日简报",
            enabled=default_enabled,
            run_time=default_run_time,
            timezone=default_timezone,
        )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._migrate_legacy_schedule()

    def list_schedules(self, *, enabled_only: bool = False) -> list[DailyBriefSchedule]:
        query = "SELECT * FROM daily_brief_schedules"
        parameters: tuple[object, ...] = ()
        if enabled_only:
            query += " WHERE enabled = ?"
            parameters = (1,)
        query += " ORDER BY run_time ASC, created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [self._row_to_schedule(row) for row in rows]

    def get(self, schedule_id: str | None = None) -> DailyBriefSchedule:
        with self._connect() as conn:
            if schedule_id:
                row = conn.execute(
                    "SELECT * FROM daily_brief_schedules WHERE schedule_id = ?",
                    (schedule_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM daily_brief_schedules ORDER BY created_at ASC LIMIT 1"
                ).fetchone()
        if row is None:
            if schedule_id:
                raise KeyError(schedule_id)
            return self.save(self._default_schedule)
        return self._row_to_schedule(row)

    def save(self, schedule: DailyBriefSchedule) -> DailyBriefSchedule:
        now = datetime.now(UTC).isoformat()
        created_at = schedule.created_at or now
        saved = schedule.model_copy(update={"created_at": created_at, "updated_at": now})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_brief_schedules
                    (schedule_id, name, enabled, run_time, timezone, last_run_date,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    name = excluded.name,
                    enabled = excluded.enabled,
                    run_time = excluded.run_time,
                    timezone = excluded.timezone,
                    last_run_date = excluded.last_run_date,
                    updated_at = excluded.updated_at
                """,
                (
                    saved.schedule_id,
                    saved.name,
                    1 if saved.enabled else 0,
                    saved.run_time,
                    saved.timezone,
                    saved.last_run_date,
                    saved.created_at,
                    saved.updated_at,
                ),
            )
        return saved

    def delete(self, schedule_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM daily_brief_schedules WHERE schedule_id = ?",
                (schedule_id,),
            )
        return cursor.rowcount > 0

    def mark_run_date(self, schedule_id: str, local_date: str) -> DailyBriefSchedule:
        schedule = self.get(schedule_id)
        return self.save(schedule.model_copy(update={"last_run_date": local_date}))

    def has_enabled(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM daily_brief_schedules WHERE enabled = 1 LIMIT 1"
            ).fetchone()
        return row is not None

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_brief_schedules (
                    schedule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    run_time TEXT NOT NULL DEFAULT '08:00',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                    last_run_date TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_brief_schedules_due
                ON daily_brief_schedules(enabled, run_time)
                """
            )

    def _migrate_legacy_schedule(self) -> None:
        with self._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS total FROM daily_brief_schedules"
            ).fetchone()["total"]
            if count:
                return
            legacy_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("daily_brief_schedule",),
            ).fetchone()
            if legacy_table is None:
                return
            row = conn.execute(
                "SELECT * FROM daily_brief_schedule WHERE config_id = 1"
            ).fetchone()
        if row is None:
            return
        self.save(
            self._default_schedule.model_copy(
                update={
                    "enabled": bool(row["enabled"]),
                    "run_time": row["run_time"],
                    "timezone": row["timezone"],
                    "last_run_date": row["last_run_date"],
                }
            )
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_schedule(row: sqlite3.Row) -> DailyBriefSchedule:
        return DailyBriefSchedule(
            schedule_id=row["schedule_id"],
            name=row["name"],
            enabled=bool(row["enabled"]),
            run_time=row["run_time"],
            timezone=row["timezone"],
            last_run_date=row["last_run_date"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
