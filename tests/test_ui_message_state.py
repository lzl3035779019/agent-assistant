from pmaa.storage.history_store import TaskMessage
from pmaa.ui.message_state import message_has_pending_confirmation


def test_message_with_pending_confirmation_requires_confirmation_rendering():
    message = TaskMessage(
        role="assistant",
        content="",
        created_at="2026-01-01T00:00:00Z",
        view={
            "pending_confirmation": {
                "status": "confirmation_required",
                "action": "browser.open_url",
                "plan": {"url": "https://www.baidu.com"},
            }
        },
    )

    assert message_has_pending_confirmation(message) is True


def test_message_without_pending_confirmation_uses_normal_rendering():
    message = TaskMessage(
        role="assistant",
        content="hello",
        created_at="2026-01-01T00:00:00Z",
        view={"pending_confirmation": {}},
    )

    assert message_has_pending_confirmation(message) is False
