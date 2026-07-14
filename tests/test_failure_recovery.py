from dataclasses import dataclass

from pmaa.storage.history_store import SQLiteTaskHistoryStore
from pmaa.ui.conversation_context import build_conversation_context


@dataclass
class Message:
    role: str
    content: str
    message_type: str = "normal"


def test_history_store_saves_failed_task_as_error_message(tmp_path):
    store = SQLiteTaskHistoryStore(tmp_path / "history.sqlite3")
    draft = store.create_draft("find current weather")

    saved = store.save_error(
        task_id=draft.task_id,
        user_input="find current weather",
        error_message="TAVILY_API_KEY is missing",
    )
    loaded = store.get(draft.task_id)

    assert loaded is not None
    assert saved.view["status"] == "failed"
    assert loaded.view["status"] == "failed"
    assert loaded.view["error"] == "TAVILY_API_KEY is missing"
    assert [message.role for message in loaded.messages] == ["user", "assistant"]
    assert loaded.messages[1].message_type == "error"
    assert loaded.messages[1].content == "TAVILY_API_KEY is missing"


def test_conversation_context_skips_error_messages():
    context = build_conversation_context(
        [
            Message(role="user", content="search current weather"),
            Message(
                role="assistant",
                content="TAVILY_API_KEY is missing",
                message_type="error",
            ),
            Message(role="user", content="retry it"),
        ]
    )

    assert "TAVILY_API_KEY is missing" not in context
    assert "search current weather" in context
    assert "retry it" in context
