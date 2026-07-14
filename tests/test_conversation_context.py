from dataclasses import dataclass

from pmaa.ui.conversation_context import build_conversation_context


@dataclass
class Message:
    role: str
    content: str


def test_build_conversation_context_formats_recent_messages():
    context = build_conversation_context(
        [
            Message(role="user", content="LangGraph 是什么？"),
            Message(role="assistant", content="LangGraph 用于构建有状态 Agent。"),
            Message(role="user", content="那它适合做什么？"),
        ],
        limit=2,
    )

    assert "LangGraph 是什么" not in context
    assert "助手：LangGraph 用于构建有状态 Agent。" in context
    assert "用户：那它适合做什么？" in context
