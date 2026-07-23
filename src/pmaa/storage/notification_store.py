from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pmaa.schemas.notification import NotificationRecord


class SQLiteNotificationStore:
    def __init__(self, db_path: str | Path = "data/pmaa_notifications.sqlite3") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def save(self, notification: NotificationRecord) -> NotificationRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO notifications
                    (notification_id, kind, title, content, severity, source_agent,
                     related_rule_id, is_read, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification.notification_id,
                    notification.kind,
                    notification.title,
                    notification.content,
                    notification.severity,
                    notification.source_agent,
                    notification.related_rule_id,
                    1 if notification.read else 0,
                    notification.created_at,
                    json.dumps(notification.metadata, ensure_ascii=True, sort_keys=True),
                ),
            )
        return notification

    def list_notifications(
        self,
        *,
        limit: int = 50,
        unread_only: bool = False,
        kind: str | None = None,
    ) -> list[NotificationRecord]:
        limit = max(1, min(int(limit), 200))
        query = "SELECT * FROM notifications"
        conditions: list[str] = []
        parameters: list[object] = []
        if unread_only:
            conditions.append("is_read = ?")
            parameters.append(0)
        if kind:
            conditions.append("kind = ?")
            parameters.append(kind)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        parameters.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(parameters)).fetchall()
        return [self._row_to_notification(row) for row in rows]

    def count_unread(self, *, kind: str | None = None) -> int:
        query = "SELECT COUNT(*) AS total FROM notifications WHERE is_read = 0"
        parameters: tuple[object, ...] = ()
        if kind:
            query += " AND kind = ?"
            parameters = (kind,)
        with self._connect() as conn:
            row = conn.execute(query, parameters).fetchone()
        return int(row["total"])

    def mark_read(self, notification_id: str, read: bool = True) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE notifications SET is_read = ? WHERE notification_id = ?",
                (1 if read else 0, notification_id),
            )
        return cursor.rowcount > 0

    def mark_all_read(self, *, kind: str | None = None) -> int:
        query = "UPDATE notifications SET is_read = 1 WHERE is_read = 0"
        parameters: tuple[object, ...] = ()
        if kind:
            query += " AND kind = ?"
            parameters = (kind,)
        with self._connect() as conn:
            cursor = conn.execute(query, parameters)
        return cursor.rowcount

    def delete(self, notification_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM notifications WHERE notification_id = ?",
                (notification_id,),
            )
        return cursor.rowcount > 0

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'info',
                    source_agent TEXT NOT NULL DEFAULT '',
                    related_rule_id TEXT,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_read_time
                ON notifications(is_read, created_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_notification(row: sqlite3.Row) -> NotificationRecord:
        return NotificationRecord(
            notification_id=row["notification_id"],
            kind=row["kind"],
            title=row["title"],
            content=row["content"],
            severity=row["severity"],
            source_agent=row["source_agent"],
            related_rule_id=row["related_rule_id"],
            read=bool(row["is_read"]),
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"]),
        )
