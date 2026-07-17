"""Process-wide background jobs for long-running GBrain Wiki imports.

Streamlit stops the current script run whenever the user navigates.  The MCP
calls must therefore not live on that script's request thread: a preview or a
commit continues in this executor and its result can be read when the user
returns to the Wiki page.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Literal
from uuid import uuid4

from pmaa.wiki.importer import (
    WikiDeleteResult,
    WikiImportPreview,
    WikiImportResult,
    create_gbrain_wiki_service,
)
from pmaa.wiki.enrichment import GBrainSkillResult, enrich_source_with_gbrain_skills
from pmaa.wiki.semantic_model import SemanticModelResult, build_semantic_knowledge_model


WikiJobKind = Literal["preview", "commit", "delete", "enrich", "semantic_model"]
WikiJobState = Literal["queued", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class WikiImportJob:
    job_id: str
    kind: WikiJobKind
    state: WikiJobState
    created_at: str
    completed_at: str = ""
    result: WikiImportPreview | WikiImportResult | WikiDeleteResult | GBrainSkillResult | SemanticModelResult | None = None
    error: str = ""


@dataclass
class _JobRecord:
    job_id: str
    kind: WikiJobKind
    state: WikiJobState
    created_at: str
    completed_at: str = ""
    result: WikiImportPreview | WikiImportResult | WikiDeleteResult | GBrainSkillResult | SemanticModelResult | None = None
    error: str = ""


# One worker deliberately serializes writes to the local GBrain/PGlite store.
# Queued jobs remain durable for the lifetime of the PMAA process, regardless
# of Streamlit page navigation or reruns.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gbrain-wiki")
_LOCK = Lock()
_JOBS: dict[str, _JobRecord] = {}


def start_wiki_preview_job(
    filename: str,
    data: bytes,
    title: str | None = None,
) -> WikiImportJob:
    return _start_job(
        "preview",
        lambda: _run_preview(filename=filename, data=data, title=title),
    )


def start_wiki_commit_job(import_id: str) -> WikiImportJob:
    return _start_job("commit", lambda: _run_commit(import_id))


def start_wiki_delete_source_job(source_slug: str) -> WikiImportJob:
    return _start_job("delete", lambda: create_gbrain_wiki_service().delete_source(source_slug))


def start_gbrain_skill_enrichment_job(source_slug: str) -> WikiImportJob:
    return _start_job("enrich", lambda: enrich_source_with_gbrain_skills(source_slug))


def start_semantic_knowledge_model_job(source_slug: str) -> WikiImportJob:
    return _start_job("semantic_model", lambda: build_semantic_knowledge_model(source_slug))


def get_wiki_import_job(job_id: str | None) -> WikiImportJob | None:
    if not job_id:
        return None
    with _LOCK:
        record = _JOBS.get(job_id)
        return _snapshot(record) if record else None


def _start_job(
    kind: WikiJobKind,
    operation: Callable[[], WikiImportPreview | WikiImportResult | WikiDeleteResult | GBrainSkillResult | SemanticModelResult],
) -> WikiImportJob:
    job_id = str(uuid4())
    record = _JobRecord(
        job_id=job_id,
        kind=kind,
        state="queued",
        created_at=_now(),
    )
    with _LOCK:
        _JOBS[job_id] = record
    future = _EXECUTOR.submit(_execute, job_id, operation)
    future.add_done_callback(_consume_unexpected_future_error)
    return _snapshot(record)


def _execute(
    job_id: str,
    operation: Callable[[], WikiImportPreview | WikiImportResult | WikiDeleteResult | GBrainSkillResult | SemanticModelResult],
) -> None:
    with _LOCK:
        record = _JOBS[job_id]
        record.state = "running"
    try:
        result = operation()
    except Exception as exc:
        with _LOCK:
            record = _JOBS[job_id]
            record.state = "failed"
            record.error = _format_job_error(exc)
            record.completed_at = _now()
        return
    with _LOCK:
        record = _JOBS[job_id]
        record.state = "succeeded"
        record.result = result
        record.completed_at = _now()


def _run_preview(filename: str, data: bytes, title: str | None) -> WikiImportPreview:
    service = create_gbrain_wiki_service()
    if not service.has_high_level_tools():
        raise RuntimeError(
            "GBrain MCP 尚未暴露高层 Wiki 工具：wiki_import_preview / "
            "wiki_import_commit / wiki_search / wiki_get_page / wiki_visualize。"
        )
    return service.import_preview(filename=filename, data=data, title=title)


def _run_commit(import_id: str) -> WikiImportResult:
    return create_gbrain_wiki_service().import_commit(import_id)


def _snapshot(record: _JobRecord) -> WikiImportJob:
    return WikiImportJob(
        job_id=record.job_id,
        kind=record.kind,
        state=record.state,
        created_at=record.created_at,
        completed_at=record.completed_at,
        result=record.result,
        error=record.error,
    )


def _consume_unexpected_future_error(future: Future[Any]) -> None:
    # _execute catches operation errors. Calling result() here prevents an
    # executor-level exception from being silently ignored without touching UI
    # state (for example, an unexpected programming error before the try block).
    future.result()


def _format_job_error(exc: BaseException) -> str:
    lines = [str(exc) or exc.__class__.__name__]
    if isinstance(exc, BaseExceptionGroup):
        for nested in _flatten_exception_group(exc):
            lines.append(f"{nested.__class__.__name__}: {nested}")
    return "\n".join(dict.fromkeys(line for line in lines if line))


def _flatten_exception_group(exc: BaseExceptionGroup) -> list[BaseException]:
    nested_errors: list[BaseException] = []
    for nested in exc.exceptions:
        if isinstance(nested, BaseExceptionGroup):
            nested_errors.extend(_flatten_exception_group(nested))
        else:
            nested_errors.append(nested)
    return nested_errors


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
