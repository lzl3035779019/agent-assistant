import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from pmaa.workflow.state import WorkflowResult


class TaskMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    message_type: Literal["normal", "error"] = "normal"
    view: dict[str, Any] | None = None


class TaskHistoryRecord(BaseModel):
    task_id: str
    title: str
    user_input: str
    view: dict[str, Any]
    created_at: str
    pinned: bool = False
    messages: list[TaskMessage] = []


class SQLiteTaskHistoryStore:
    def __init__(self, db_path: str | Path = "data/pmaa_history.sqlite3") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_draft(self, user_input: str = "") -> TaskHistoryRecord:
        if not user_input.strip():
            self._delete_empty_drafts()
        record = TaskHistoryRecord(
            task_id=str(uuid4()),
            title=self._make_title(user_input),
            user_input=user_input,
            view=self._empty_view(),
            created_at=datetime.now(UTC).isoformat(),
            pinned=False,
            messages=[],
        )
        self._upsert(record)
        return record

    def update_draft(self, task_id: str, user_input: str) -> TaskHistoryRecord:
        current = self.get(task_id)
        if current is None:
            raise ValueError(f"Draft task does not exist: {task_id}")
        old_auto_title = self._make_title(current.user_input)
        next_title = (
            self._make_title(user_input)
            if current.title == old_auto_title
            else current.title
        )
        record = TaskHistoryRecord(
            task_id=task_id,
            title=next_title,
            user_input=user_input,
            view={**current.view, "status": "draft"},
            created_at=datetime.now(UTC).isoformat(),
            pinned=current.pinned,
            messages=getattr(current, "messages", []),
        )
        self._upsert(record)
        return record

    def set_pinned(self, task_id: str, pinned: bool) -> TaskHistoryRecord:
        current = self._require_record(task_id)
        record = current.model_copy(update={"pinned": pinned})
        self._upsert(record)
        return record

    def rename(self, task_id: str, title: str) -> TaskHistoryRecord:
        clean_title = self._make_title(title)
        current = self._require_record(task_id)
        record = current.model_copy(update={"title": clean_title})
        self._upsert(record)
        return record

    def delete(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM task_history WHERE task_id = ?", (task_id,))

    def save_result(
        self,
        result: WorkflowResult,
        view: dict[str, Any],
        task_id: str | None = None,
    ) -> TaskHistoryRecord:
        active_task_id = task_id or result.task_id or self._task_id_from_events(result)
        current = self.get(active_task_id)
        next_title = self._make_title(result.user_input)
        if current and (
            getattr(current, "messages", [])
            or current.title != self._make_title(current.user_input)
        ):
            next_title = current.title
        messages = list(getattr(current, "messages", [])) if current else []
        timestamp = datetime.now(UTC).isoformat()
        messages.extend(
            [
                TaskMessage(role="user", content=result.user_input, created_at=timestamp),
                TaskMessage(
                    role="assistant",
                    content=view.get("answer", ""),
                    created_at=timestamp,
                    view={**view, "status": "completed"},
                ),
            ]
        )
        record = TaskHistoryRecord(
            task_id=active_task_id,
            title=next_title,
            user_input=result.user_input,
            view={**view, "status": "completed"},
            created_at=timestamp,
            pinned=current.pinned if current else False,
            messages=messages,
        )
        self._upsert(record)
        return record

    def save_error(
        self,
        task_id: str,
        user_input: str,
        error_message: str,
    ) -> TaskHistoryRecord:
        current = self.get(task_id)
        timestamp = datetime.now(UTC).isoformat()
        empty_view = self._empty_view()
        view = {
            **empty_view,
            "status": "failed",
            "answer": "",
            "error": error_message,
            "metrics": {
                **empty_view["metrics"],
                "reflection_status": "failed",
            },
        }
        messages = list(getattr(current, "messages", [])) if current else []
        next_title = self._make_title(user_input)
        if current and (
            getattr(current, "messages", [])
            or current.title != self._make_title(current.user_input)
        ):
            next_title = current.title
        messages.extend(
            [
                TaskMessage(role="user", content=user_input, created_at=timestamp),
                TaskMessage(
                    role="assistant",
                    content=error_message,
                    created_at=timestamp,
                    message_type="error",
                    view=view,
                ),
            ]
        )
        record = TaskHistoryRecord(
            task_id=task_id,
            title=next_title,
            user_input=user_input,
            view=view,
            created_at=timestamp,
            pinned=current.pinned if current else False,
            messages=messages,
        )
        self._upsert(record)
        return record

    def replace_view(self, task_id: str, view: dict[str, Any]) -> TaskHistoryRecord:
        current = self._require_record(task_id)
        messages = list(getattr(current, "messages", []))
        if messages:
            messages[-1] = messages[-1].model_copy(update={"content": view.get("answer", ""), "view": view})
        record = current.model_copy(update={"view": view, "messages": messages})
        self._upsert(record)
        return record

    def get(self, task_id: str) -> TaskHistoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT task_id, title, user_input, view_json, created_at, pinned, messages_json
                FROM task_history
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_recent(self, limit: int = 20) -> list[TaskHistoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, title, user_input, view_json, created_at, pinned, messages_json
                FROM task_history
                ORDER BY pinned DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _upsert(self, record: TaskHistoryRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_history
                    (task_id, title, user_input, view_json, created_at, pinned, messages_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_id,
                    record.title,
                    record.user_input,
                    json.dumps(record.view, ensure_ascii=False),
                    record.created_at,
                    1 if record.pinned else 0,
                    json.dumps(
                        [message.model_dump() for message in record.messages],
                        ensure_ascii=False,
                    ),
                ),
            )

    def _delete_empty_drafts(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, view_json
                FROM task_history
                WHERE TRIM(user_input) = ''
                """
            ).fetchall()
            empty_draft_ids = [
                row["task_id"]
                for row in rows
                if json.loads(row["view_json"]).get("status") == "draft"
            ]
            conn.executemany(
                "DELETE FROM task_history WHERE task_id = ?",
                [(task_id,) for task_id in empty_draft_ids],
            )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_history (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    view_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    messages_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(task_history)").fetchall()
            }
            if "pinned" not in columns:
                conn.execute(
                    "ALTER TABLE task_history ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                )
            if "messages_json" not in columns:
                conn.execute(
                    "ALTER TABLE task_history ADD COLUMN messages_json TEXT NOT NULL DEFAULT '[]'"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_record(self, row: sqlite3.Row) -> TaskHistoryRecord:
        return TaskHistoryRecord(
            task_id=row["task_id"],
            title=row["title"],
            user_input=row["user_input"],
            view=json.loads(row["view_json"]),
            created_at=row["created_at"],
            pinned=bool(row["pinned"]),
            messages=[
                TaskMessage(**message)
                for message in json.loads(row["messages_json"] or "[]")
            ],
        )

    def _require_record(self, task_id: str) -> TaskHistoryRecord:
        record = self.get(task_id)
        if record is None:
            raise ValueError(f"Task history record does not exist: {task_id}")
        return record

    @staticmethod
    def _make_title(user_input: str) -> str:
        title = user_input.strip().replace("\n", " ")
        return title[:32] or "新对话"

    @staticmethod
    def _empty_view() -> dict[str, Any]:
        return {
            "status": "draft",
            "answer": "",
            "sources": [],
            "source_references": [],
            "action_audit": [],
            "reflection": {"passed": False, "issues": []},
            "metrics": {
                "agent_count": 0,
                "source_count": 0,
                "reflection_status": "未运行",
                "llm_model": "",
            },
            "events": [],
        }

    @staticmethod
    def _task_id_from_events(result: WorkflowResult) -> str:
        if result.events:
            return result.events[0].task_id
        raise ValueError("WorkflowResult has no task_id or events.")
