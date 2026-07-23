from pmaa.agents.email import EmailAgent
from pmaa.agents.policy import PolicyAgent
from pmaa.skills.confirmation import confirm_pending_action
from pmaa.skills.executors import ActionExecutorRegistry
from email.message import EmailMessage

from pmaa.tools.email_tool import EmailSummary, EmailTool, _message_text


class FakeEmailBackend:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.marked_read: list[str] = []

    def list_recent(self, limit: int = 5, unread_only: bool = False):
        return [
            EmailSummary(
                message_id="1",
                from_addr="sender@example.com",
                subject="Project Update",
                date="Thu, 16 Jul 2026 10:00:00 +0800",
                snippet="Please sync the project progress.",
                unread=True,
            )
        ][:limit]

    def count_unread(self) -> int:
        return 3

    def count_today_unread(self) -> int:
        return 2

    def get_message(self, message_id: str, mark_read: bool = False):
        if message_id != "1":
            return None
        if mark_read:
            self.marked_read.append(message_id)
        return EmailSummary(
            message_id="1",
            from_addr="sender@example.com",
            subject="Project Update",
            date="Thu, 16 Jul 2026 10:00:00 +0800",
            snippet="Please sync the project progress.",
            unread=not mark_read,
            body="Full message body for project progress.",
        )

    def send(self, to: str, subject: str, body: str) -> str:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return "<fake-message-id>"


def test_policy_routes_email_query_to_email_tool():
    decision = PolicyAgent().decide("check my QQ email inbox")

    assert decision.required_tool == "email"
    assert decision.execution_mode == "tool_call"
    assert decision.requires_confirmation is False


def test_email_agent_builds_prepare_send_request():
    request = EmailAgent().build_tool_request(
        "send email to test@example.com subject: Hello body: This is a test"
    )

    assert request["action"] == "prepare_send"
    assert request["to"] == "test@example.com"
    assert request["subject"] == "Hello"
    assert request["body"] == "This is a test"


def test_email_tool_lists_recent_messages():
    result = EmailTool(FakeEmailBackend()).__call__({"action": "list_recent", "limit": 1})

    assert result["status"] == "completed"
    assert "Project Update" in result["answer"]
    assert result["messages"][0]["unread"] is True


def test_email_tool_counts_unread_messages():
    result = EmailTool(FakeEmailBackend()).__call__({"action": "count_unread"})

    assert result["status"] == "completed"
    assert result["unread_count"] == 3


def test_email_tool_counts_today_unread_messages():
    result = EmailTool(FakeEmailBackend()).__call__({"action": "count_today_unread"})

    assert result["status"] == "completed"
    assert result["unread_count"] == 2


def test_email_tool_filters_recent_messages_to_target_date():
    tool = EmailTool(FakeEmailBackend())

    matching = tool(
        {
            "action": "list_recent",
            "unread_only": True,
            "today_only": True,
            "target_date": "2026-07-16",
        }
    )
    missing = tool(
        {
            "action": "list_recent",
            "unread_only": True,
            "today_only": True,
            "target_date": "2026-07-17",
        }
    )

    assert len(matching["messages"]) == 1
    assert missing["messages"] == []
    assert "今日未读邮件" in missing["answer"]


def test_email_tool_gets_selected_message_body():
    result = EmailTool(FakeEmailBackend()).__call__(
        {"action": "get_message", "message_id": "1"}
    )

    assert result["status"] == "completed"
    assert result["message"]["body"] == "Full message body for project progress."


def test_email_tool_marks_message_read_when_requested():
    backend = FakeEmailBackend()
    result = EmailTool(backend).__call__(
        {"action": "get_message", "message_id": "1", "mark_read": True}
    )

    assert result["status"] == "completed"
    assert result["message"]["unread"] is False
    assert backend.marked_read == ["1"]


def test_email_tool_drafts_reply_from_selected_message():
    result = EmailTool(FakeEmailBackend()).__call__(
        {"action": "draft_reply", "message_id": "1"}
    )

    assert result["status"] == "completed"
    assert result["draft"]["source_message_id"] == "1"
    assert result["draft"]["to"] == "sender@example.com"


def test_email_tool_extracts_html_only_message_text():
    message = EmailMessage()
    message["Subject"] = "HTML"
    message.set_content("<p>Hello<br>World</p>", subtype="html")

    assert _message_text(message) == "Hello\nWorld"


def test_email_tool_requires_confirmation_before_send():
    result = EmailTool(FakeEmailBackend()).__call__(
        {
            "action": "prepare_send",
            "to": "test@example.com",
            "subject": "Hello",
            "body": "Hi",
        }
    )

    assert result["status"] == "confirmation_required"
    assert result["action"] == "email.send"
    assert result["permission_level"] == "dangerous"
    assert result["plan"]["to"] == "test@example.com"


def test_confirm_pending_email_send_executes_only_after_approval():
    registry = ActionExecutorRegistry()
    sent: list[dict] = []
    registry.register(
        "email.send",
        lambda plan: sent.append(plan) or {"status": "executed", "message_id": "1"},
    )
    pending = EmailTool(FakeEmailBackend()).__call__(
        {
            "action": "prepare_send",
            "to": "test@example.com",
            "subject": "Hello",
            "body": "Hi",
        }
    )

    rejected = confirm_pending_action(pending, approved=False, executor_registry=registry)
    approved = confirm_pending_action(pending, approved=True, executor_registry=registry)

    assert rejected["status"] == "rejected_by_user"
    assert approved["status"] == "executed"
    assert sent == [pending["plan"]]
