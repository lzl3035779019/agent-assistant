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
