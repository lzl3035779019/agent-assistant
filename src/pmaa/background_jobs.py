from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from pmaa.schemas.background_job import BackgroundJob, BackgroundJobStatus
from pmaa.storage.background_job_store import SQLiteBackgroundJobStore


WorkflowStream = Callable[..., Iterator[dict[str, Any]]]
JobCallback = Callable[[BackgroundJob], None]


class BackgroundJobManager:
    def __init__(
        self,
        *,
        store: SQLiteBackgroundJobStore,
        workflow_stream: WorkflowStream,
        max_workers: int = 4,
        on_completed: JobCallback | None = None,
    ) -> None:
        self.store = store
        self.workflow_stream = workflow_stream
        self.on_completed = on_completed
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="pmaa-background-job",
        )

    def submit_multi_agent(
        self,
        *,
        user_input: str,
        conversation_context: str = "",
        kind: str = "chat",
        label: str = "Agent 任务",
        metadata: dict[str, Any] | None = None,
        assigned_agent: str = "",
    ) -> BackgroundJob:
        job = self.store.save(
            BackgroundJob(
                kind=kind,
                label=label,
                request={
                    "user_input": user_input,
                    "conversation_context": conversation_context,
                    "metadata": metadata or {},
                    "assigned_agent": assigned_agent,
                },
            )
        )
        self._executor.submit(self._run_multi_agent, job.job_id)
        return job

    def shutdown(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run_multi_agent(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        started_at = datetime.now(UTC).isoformat()
        job = self.store.save(
            job.model_copy(
                update={
                    "status": BackgroundJobStatus.RUNNING,
                    "started_at": started_at,
                    "progress": {"events": [], "message": "任务开始执行。"},
                }
            )
        )
        events: list[dict[str, Any]] = []
        completed_result: dict[str, Any] | None = None
        try:
            stream_arguments = (
                str(job.request.get("user_input", "")),
                str(job.request.get("conversation_context", "")),
            )
            assigned_agent = str(job.request.get("assigned_agent", "")).strip()
            stream = (
                self.workflow_stream(*stream_arguments, assigned_agent=assigned_agent)
                if assigned_agent
                else self.workflow_stream(*stream_arguments)
            )
            for stream_event in stream:
                event_type = stream_event.get("type")
                if event_type == "agent_event":
                    event_payload = self._jsonable(stream_event.get("event", {}))
                    if not isinstance(event_payload, dict):
                        continue
                    events.append(event_payload)
                    job = self.store.save(
                        job.model_copy(
                            update={
                                "progress": {
                                    "events": events[-300:],
                                    "message": "Agent 正在协作执行。",
                                }
                            }
                        )
                    )
                elif event_type == "workflow_completed":
                    completed_result = self._jsonable(stream_event.get("result", {}))
                elif event_type == "workflow_error":
                    raise RuntimeError(str(stream_event.get("error") or "后台任务失败"))
            if completed_result is None:
                raise RuntimeError("后台工作流结束但没有返回结果。")
            completed_at = datetime.now(UTC).isoformat()
            job = self.store.save(
                job.model_copy(
                    update={
                        "status": BackgroundJobStatus.COMPLETED,
                        "result": completed_result,
                        "progress": {
                            "events": events[-300:],
                            "message": "任务已完成。",
                        },
                        "completed_at": completed_at,
                        "error": "",
                    }
                )
            )
            if self.on_completed is not None:
                try:
                    self.on_completed(job)
                except Exception:
                    pass
        except Exception as exc:
            failed_at = datetime.now(UTC).isoformat()
            self.store.save(
                job.model_copy(
                    update={
                        "status": BackgroundJobStatus.FAILED,
                        "error": str(exc),
                        "completed_at": failed_at,
                        "progress": {
                            "events": events[-300:],
                            "message": "任务执行失败。",
                        },
                    }
                )
            )

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {key: cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._jsonable(item) for item in value]
        return value
