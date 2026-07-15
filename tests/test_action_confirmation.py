from pmaa.skills.confirmation import confirm_pending_action
from pmaa.skills.executors import create_default_executor_registry


PENDING_CONFIRMATION = {
    "status": "confirmation_required",
    "tool_name": "skill:agent_browser",
    "skill_id": "agent_browser",
    "action": "browser.open_url",
    "permission_level": "network",
    "requires_confirmation": True,
    "plan": {"url": "https://example.com"},
    "rollback": {"status": "not_started"},
}

BROWSER_TASK_CONFIRMATION = {
    "status": "confirmation_required",
    "tool_name": "skill:agent_browser",
    "skill_id": "agent_browser",
    "action": "browser.task",
    "permission_level": "network",
    "requires_confirmation": True,
    "plan": {
        "goal": "打开示例网站并截图",
        "start_url": "https://example.com",
        "steps": ["打开网页", "截图"],
        "command_plan": [
            "agent-browser open https://example.com",
            "agent-browser screenshot",
        ],
    },
    "rollback": {"status": "not_started"},
}


def test_confirm_pending_action_executes_approved_browser_open_url():
    opened_urls: list[str] = []
    executor_registry = create_default_executor_registry(
        browser_opener=lambda url: opened_urls.append(url) or True
    )

    result = confirm_pending_action(
        PENDING_CONFIRMATION,
        approved=True,
        executor_registry=executor_registry,
    )

    assert result["approved"] is True
    assert result["status"] == "executed"
    assert result["action"] == "browser.open_url"
    assert result["permission_level"] == "network"
    assert result["plan"]["url"] == "https://example.com"
    assert result["execution"]["status"] == "executed"
    assert opened_urls == ["https://example.com"]


def test_confirm_pending_action_records_user_rejection():
    result = confirm_pending_action(PENDING_CONFIRMATION, approved=False)

    assert result["approved"] is False
    assert result["status"] == "rejected_by_user"
    assert result["action"] == "browser.open_url"
    assert result["execution"]["status"] == "cancelled"


def test_confirm_pending_action_executes_approved_browser_task_commands():
    commands: list[list[str]] = []
    executor_registry = create_default_executor_registry(
        command_exists=lambda command: command == "agent-browser",
        command_runner=lambda command, timeout: commands.append(command) or (0, "ok", ""),
    )

    result = confirm_pending_action(
        BROWSER_TASK_CONFIRMATION,
        approved=True,
        executor_registry=executor_registry,
    )

    assert result["approved"] is True
    assert result["status"] == "executed"
    assert result["action"] == "browser.task"
    assert result["execution"]["status"] == "executed"
    assert commands == [
        ["agent-browser", "open", "https://example.com"],
        ["agent-browser", "screenshot"],
    ]


def test_confirm_pending_action_reports_missing_agent_browser_runtime():
    executor_registry = create_default_executor_registry(
        command_exists=lambda command: False,
    )

    result = confirm_pending_action(
        BROWSER_TASK_CONFIRMATION,
        approved=True,
        executor_registry=executor_registry,
    )

    assert result["approved"] is True
    assert result["status"] == "failed"
    assert result["execution"]["status"] == "missing_runtime"
