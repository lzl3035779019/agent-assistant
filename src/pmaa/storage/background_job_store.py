from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pmaa.schemas.background_job import BackgroundJob, BackgroundJobStatus


class SQLiteBackgroundJobStore:
    def __init__(self, db_path: str | Path = "data/pmaa_jobs.sqlite3") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def save(self, job: BackgroundJob) -> BackgroundJob:
        saved = job.model_copy(update={"updated_at": datetime.now(UTC).isoformat()})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO background_jobs
                    (job_id, kind, label, status, request_json, progress_json,
                     result_json, error, created_at, started_at, completed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    saved.job_id,
                    saved.kind,
                    saved.label,
                    saved.status.value,
                    json.dumps(saved.request, ensure_ascii=False),
                    json.dumps(saved.progress, ensure_ascii=False),
                    json.dumps(saved.result, ensure_ascii=False),
                    saved.error,
                    saved.created_at,
                    saved.started_at,
                    saved.completed_at,
                    saved.updated_at,
                ),
            )
        return saved

    def get(self, job_id: str) -> BackgroundJob | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM background_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, *, kind: str = "", limit: int = 20) -> list[BackgroundJob]:
        query = "SELECT * FROM background_jobs"
        parameters: list[Any] = []
        if kind:
            query += " WHERE kind = ?"
            parameters.append(kind)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(max(1, min(limit, 100)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(parameters)).fetchall()
        return [self._row_to_job(row) for row in rows]

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS background_jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    progress_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_background_jobs_kind_created
                ON background_jobs(kind, created_at DESC)
                """
            )

    def recover_interrupted_jobs(self) -> int:
        """Mark jobs left active by a previous API process as failed."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE background_jobs
                SET status = ?, error = ?, completed_at = ?, updated_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    BackgroundJobStatus.FAILED.value,
                    "服务重启，原后台任务已中断，请重新运行。",
                    now,
                    now,
                    BackgroundJobStatus.PENDING.value,
                    BackgroundJobStatus.RUNNING.value,
                ),
            )
        return max(0, cursor.rowcount)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> BackgroundJob:
        return BackgroundJob(
            job_id=row["job_id"],
            kind=row["kind"],
            label=row["label"],
            status=row["status"],
            request=json.loads(row["request_json"]),
            progress=json.loads(row["progress_json"]),
            result=json.loads(row["result_json"]),
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            updated_at=row["updated_at"],
        )
