from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pmaa.schemas.monitor import MonitorRule, MonitorSnapshot


class SQLiteMonitorStore:
    def __init__(self, db_path: str | Path = "data/pmaa_monitor.sqlite3") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def save_rule(self, rule: MonitorRule) -> MonitorRule:
        now = datetime.now(UTC).isoformat()
        existing = self.get_rule(rule.rule_id)
        saved = rule.model_copy(
            update={
                "created_at": existing.created_at if existing else rule.created_at,
                "updated_at": now,
            }
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO monitor_rules
                    (rule_id, name, target_type, target, query, enabled,
                     interval_minutes, created_at, updated_at, last_run_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    saved.rule_id,
                    saved.name,
                    saved.target_type,
                    saved.target,
                    saved.query,
                    1 if saved.enabled else 0,
                    saved.interval_minutes,
                    saved.created_at,
                    saved.updated_at,
                    saved.last_run_at,
                ),
            )
        return saved

    def get_rule(self, rule_id: str) -> MonitorRule | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM monitor_rules WHERE rule_id = ?",
                (rule_id,),
            ).fetchone()
        return self._row_to_rule(row) if row else None

    def list_rules(self, *, enabled_only: bool = False) -> list[MonitorRule]:
        query = "SELECT * FROM monitor_rules"
        parameters: tuple[Any, ...] = ()
        if enabled_only:
            query += " WHERE enabled = ?"
            parameters = (1,)
        query += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, parameters).fetchall()
        return [self._row_to_rule(row) for row in rows]

    def delete_rule(self, rule_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM monitor_rules WHERE rule_id = ?",
                (rule_id,),
            )
        return cursor.rowcount > 0

    def mark_run(self, rule_id: str, observed_at: str | None = None) -> MonitorRule:
        current = self.get_rule(rule_id)
        if current is None:
            raise ValueError(f"Monitor rule does not exist: {rule_id}")
        run_at = observed_at or datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE monitor_rules
                SET last_run_at = ?, updated_at = ?
                WHERE rule_id = ?
                """,
                (run_at, run_at, rule_id),
            )
        return self.get_rule(rule_id)  # type: ignore[return-value]

    def save_snapshot(
        self,
        rule_id: str,
        items: list[dict[str, Any]],
    ) -> MonitorSnapshot:
        if self.get_rule(rule_id) is None:
            raise ValueError(f"Monitor rule does not exist: {rule_id}")
        snapshot = MonitorSnapshot(
            rule_id=rule_id,
            fingerprint=self.fingerprint(items),
            items=items,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO monitor_snapshots
                    (snapshot_id, rule_id, fingerprint, items_json, observed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.rule_id,
                    snapshot.fingerprint,
                    json.dumps(snapshot.items, ensure_ascii=True, sort_keys=True),
                    snapshot.observed_at,
                ),
            )
            conn.execute(
                """
                UPDATE monitor_rules
                SET last_run_at = ?, updated_at = ?
                WHERE rule_id = ?
                """,
                (snapshot.observed_at, snapshot.observed_at, rule_id),
            )
        return snapshot

    def latest_snapshot(self, rule_id: str) -> MonitorSnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT snapshot_id, rule_id, fingerprint, items_json, observed_at
                FROM monitor_snapshots
                WHERE rule_id = ?
                ORDER BY observed_at DESC, rowid DESC
                LIMIT 1
                """,
                (rule_id,),
            ).fetchone()
        if row is None:
            return None
        return MonitorSnapshot(
            snapshot_id=row["snapshot_id"],
            rule_id=row["rule_id"],
            fingerprint=row["fingerprint"],
            items=json.loads(row["items_json"]),
            observed_at=row["observed_at"],
        )

    @staticmethod
    def fingerprint(items: list[dict[str, Any]]) -> str:
        normalized = json.dumps(items, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    query TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    interval_minutes INTEGER NOT NULL DEFAULT 360,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    FOREIGN KEY(rule_id) REFERENCES monitor_rules(rule_id)
                        ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_monitor_snapshots_rule_time
                ON monitor_snapshots(rule_id, observed_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> MonitorRule:
        return MonitorRule(
            rule_id=row["rule_id"],
            name=row["name"],
            target_type=row["target_type"],
            target=row["target"],
            query=row["query"],
            enabled=bool(row["enabled"]),
            interval_minutes=row["interval_minutes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_run_at=row["last_run_at"],
        )
