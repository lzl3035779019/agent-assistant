from typing import Protocol


class ConversationMessage(Protocol):
    role: str
    content: str
    message_type: str


def build_conversation_context(
    messages: list[ConversationMessage],
    limit: int = 8,
    max_content_length: int = 1200,
) -> str:
    if not messages:
        return ""

    lines = []
    for message in messages[-limit:]:
        if getattr(message, "message_type", "normal") == "error":
            continue
        role = "用户" if message.role == "user" else "助手"
        content = message.content.strip()
        if len(content) > max_content_length:
            content = content[:max_content_length] + "..."
        lines.append(f"{role}：{content}")
    return "\n".join(lines)
