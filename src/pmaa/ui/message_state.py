from typing import Any


def message_has_pending_confirmation(message: Any) -> bool:
    view = getattr(message, "view", None) or {}
    return bool(view.get("pending_confirmation"))
