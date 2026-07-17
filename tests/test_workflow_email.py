import pmaa.workflow.graph as graph_module
from pmaa.tools.email_tool import EmailSummary, EmailTool
from pmaa.workflow.graph import run_workflow


class FakeEmailBackend:
    def list_recent(self, limit: int = 5, unread_only: bool = False):
        return [
            EmailSummary(
                message_id="1",
                from_addr="sender@example.com",
                subject="面试邀约",
                date="Thu, 16 Jul 2026 10:00:00 +0800",
                snippet="请确认明天是否方便面试。",
                unread=True,
            )
        ]


def test_workflow_routes_email_query_to_email_agent(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "create_email_tool",
        lambda: EmailTool(FakeEmailBackend()),
    )

    result = run_workflow("看看 QQ 邮箱最近有没有新邮件")

    assert result.final_result is not None
    assert "面试邀约" in result.final_result.answer
    assert any(event.agent == "email" for event in result.events)
