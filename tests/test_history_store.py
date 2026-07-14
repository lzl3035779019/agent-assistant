from pmaa.storage.history_store import SQLiteTaskHistoryStore
from pmaa.ui.view_model import build_task_view
from pmaa.workflow.graph import run_workflow


def test_history_store_saves_and_loads_workflow_view(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    result = run_workflow("帮我研究 LangGraph")
    view = build_task_view(result)

    saved = store.save_result(result, view)
    loaded = store.get(saved.task_id)

    assert loaded is not None
    assert loaded.task_id == saved.task_id
    assert loaded.user_input == "帮我研究 LangGraph"
    assert loaded.view["answer"] == view["answer"]
    assert loaded.view["sources"]


def test_history_store_lists_recent_tasks_newest_first(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    first = run_workflow("第一个任务")
    second = run_workflow("第二个任务")

    first_record = store.save_result(first, build_task_view(first))
    second_record = store.save_result(second, build_task_view(second))
    recent = store.list_recent(limit=10)

    assert [record.task_id for record in recent] == [
        second_record.task_id,
        first_record.task_id,
    ]


def test_history_store_creates_and_updates_draft_session(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")

    draft = store.create_draft("新的空对话")
    loaded_draft = store.get(draft.task_id)

    assert loaded_draft is not None
    assert loaded_draft.title == "新的空对话"
    assert loaded_draft.view["answer"] == ""
    assert loaded_draft.view["status"] == "draft"

    result = run_workflow("新的空对话")
    completed = store.save_result(result, build_task_view(result), task_id=draft.task_id)
    loaded_completed = store.get(draft.task_id)

    assert completed.task_id == draft.task_id
    assert loaded_completed is not None
    assert loaded_completed.view["status"] == "completed"
    assert loaded_completed.view["answer"]


def test_history_store_updates_draft_without_creating_new_record(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    draft = store.create_draft()

    updated = store.update_draft(draft.task_id, "帮我查一下今天的热点")
    recent = store.list_recent(limit=10)

    assert updated.task_id == draft.task_id
    assert updated.title == "帮我查一下今天的热点"
    assert updated.user_input == "帮我查一下今天的热点"
    assert updated.view["status"] == "draft"
    assert [record.task_id for record in recent] == [draft.task_id]


def test_history_store_keeps_only_latest_empty_draft(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    first_empty = store.create_draft()
    filled_draft = store.create_draft("还没运行但已经有输入")

    second_empty = store.create_draft()
    recent = store.list_recent(limit=10)

    assert store.get(first_empty.task_id) is None
    assert store.get(filled_draft.task_id) is not None
    assert store.get(second_empty.task_id) is not None
    assert [record.task_id for record in recent] == [
        second_empty.task_id,
        filled_draft.task_id,
    ]


def test_history_store_pins_records_before_recent_order(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    first = store.create_draft("第一个对话")
    second = store.create_draft("第二个对话")

    pinned = store.set_pinned(first.task_id, True)
    recent = store.list_recent(limit=10)

    assert pinned.pinned is True
    assert [record.task_id for record in recent] == [
        first.task_id,
        second.task_id,
    ]


def test_history_store_renames_record_without_changing_input(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    record = store.create_draft("原始问题")

    renamed = store.rename(record.task_id, "新的标题")
    loaded = store.get(record.task_id)

    assert renamed.title == "新的标题"
    assert loaded is not None
    assert loaded.title == "新的标题"
    assert loaded.user_input == "原始问题"


def test_history_store_keeps_manual_title_when_draft_input_changes(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    record = store.create_draft("原始问题")
    store.rename(record.task_id, "手动标题")

    updated = store.update_draft(record.task_id, "新的输入内容")

    assert updated.title == "手动标题"
    assert updated.user_input == "新的输入内容"


def test_history_store_deletes_record(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    record = store.create_draft("待删除对话")

    store.delete(record.task_id)

    assert store.get(record.task_id) is None
    assert store.list_recent(limit=10) == []


def test_history_store_appends_messages_when_saving_results_to_same_conversation(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    draft = store.create_draft("第一轮问题")

    first_result = run_workflow("第一轮问题")
    store.save_result(first_result, build_task_view(first_result), task_id=draft.task_id)
    second_result = run_workflow("第二轮追问")
    saved = store.save_result(
        second_result,
        build_task_view(second_result),
        task_id=draft.task_id,
    )

    assert [message.role for message in saved.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert saved.messages[0].content == "第一轮问题"
    assert saved.messages[2].content == "第二轮追问"
    assert saved.messages[3].view is not None
    assert saved.title == "第一轮问题"
