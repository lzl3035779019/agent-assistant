from threading import Event
from time import monotonic, sleep

from pmaa.wiki import jobs


def test_wiki_commit_job_runs_after_the_ui_call_returns(monkeypatch):
    started = Event()
    release = Event()
    result = object()

    def fake_commit(import_id: str):
        assert import_id == "import-123"
        started.set()
        assert release.wait(timeout=2)
        return result

    monkeypatch.setattr(jobs, "_run_commit", fake_commit)

    job = jobs.start_wiki_commit_job("import-123")
    assert job.state in {"queued", "running"}
    assert started.wait(timeout=2)

    # At this point a Streamlit rerun/navigation can safely finish: the worker
    # owns the MCP call and the job remains discoverable by its ID.
    active = jobs.get_wiki_import_job(job.job_id)
    assert active is not None
    assert active.state == "running"

    release.set()
    deadline = monotonic() + 2
    completed = active
    while monotonic() < deadline:
        completed = jobs.get_wiki_import_job(job.job_id)
        if completed is not None and completed.state == "succeeded":
            break
        sleep(0.01)

    assert completed is not None
    assert completed.state == "succeeded"
    assert completed.result is result


def test_wiki_job_reports_nested_exception_group_details():
    def failing_operation():
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [
                RuntimeError("get_skill tool is not available"),
                ValueError("source page has no content"),
            ],
        )

    job = jobs._start_job("enrich", failing_operation)
    deadline = monotonic() + 2
    completed = job
    while monotonic() < deadline:
        current = jobs.get_wiki_import_job(job.job_id)
        if current is not None and current.state == "failed":
            completed = current
            break
        sleep(0.01)

    assert completed.state == "failed"
    assert "unhandled errors in a TaskGroup" in completed.error
    assert "RuntimeError: get_skill tool is not available" in completed.error
    assert "ValueError: source page has no content" in completed.error


def test_wiki_delete_source_job_runs_in_background(monkeypatch):
    result = object()

    class FakeService:
        def delete_source(self, source_slug: str):
            assert source_slug == "sources/documents/source-1"
            return result

    monkeypatch.setattr(jobs, "create_gbrain_wiki_service", lambda: FakeService())

    job = jobs.start_wiki_delete_source_job("sources/documents/source-1")
    deadline = monotonic() + 2
    completed = job
    while monotonic() < deadline:
        current = jobs.get_wiki_import_job(job.job_id)
        if current is not None and current.state == "succeeded":
            completed = current
            break
        sleep(0.01)

    assert completed.state == "succeeded"
    assert completed.result is result
