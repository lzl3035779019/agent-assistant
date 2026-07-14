from pmaa.storage.history_store import SQLiteTaskHistoryStore
from pmaa.ui.view_model import build_task_view
from pmaa.workflow.graph import run_workflow


def test_history_store_replaces_current_view_and_last_assistant_message(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    result = run_workflow("hello")
    record = store.save_result(result, build_task_view(result))
    updated_view = {
        **record.view,
        "answer": "确认结果已记录",
        "pending_confirmation": {},
        "confirmation_result": {"status": "rejected_by_user"},
        "action_audit": [
            {
                "approved": False,
                "action": "browser.open_url",
                "url": "https://example.com",
                "execution_status": "cancelled",
            }
        ],
    }

    updated = store.replace_view(record.task_id, updated_view)
    loaded = store.get(record.task_id)

    assert updated.view["answer"] == "确认结果已记录"
    assert loaded is not None
    assert loaded.view["confirmation_result"]["status"] == "rejected_by_user"
    assert loaded.view["action_audit"][0]["action"] == "browser.open_url"
    assert loaded.view["action_audit"][0]["url"] == "https://example.com"
    assert loaded.messages[-1].content == "确认结果已记录"
    assert loaded.messages[-1].view["pending_confirmation"] == {}
    assert loaded.messages[-1].view["action_audit"][0]["execution_status"] == "cancelled"
