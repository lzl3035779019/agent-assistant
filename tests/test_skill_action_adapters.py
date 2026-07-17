from pmaa.skills.actions import (
    SkillActionRequest,
    create_default_action_registry,
)


def test_default_action_registry_exposes_browser_open_url_adapter():
    registry = create_default_action_registry()
    adapter = registry.get("browser.open_url")

    assert adapter is not None
    assert adapter.action == "browser.open_url"
    assert adapter.permission_level == "network"
    assert adapter.requires_confirmation is True
    assert adapter.input_schema["required"] == ["url"]


def test_default_action_registry_exposes_browser_task_adapter():
    registry = create_default_action_registry()
    adapter = registry.get("browser.task")

    assert adapter is not None
    assert adapter.action == "browser.task"
    assert adapter.permission_level == "network"
    assert adapter.requires_confirmation is True
    assert adapter.input_schema["required"] == ["goal"]


def test_browser_open_url_requires_confirmation_and_returns_dry_run_plan():
    registry = create_default_action_registry()
    result = registry.execute(
        SkillActionRequest(
            action="browser.open_url",
            args={"url": "https://example.com"},
            confirmed=False,
        )
    )

    assert result["success"] is False
    assert result["status"] == "confirmation_required"
    assert result["action"] == "browser.open_url"
    assert result["permission_level"] == "network"
    assert result["requires_confirmation"] is True
    assert result["dry_run"] is True
    assert result["plan"]["url"] == "https://example.com"
    assert result["rollback"]["status"] == "not_started"


def test_browser_task_requires_confirmation_and_returns_agent_browser_plan():
    registry = create_default_action_registry()
    result = registry.execute(
        SkillActionRequest(
            action="browser.task",
            args={
                "goal": "打开示例网站并截图",
                "start_url": "https://example.com",
                "steps": ["打开页面", "截图"],
            },
            confirmed=False,
        )
    )

    assert result["success"] is False
    assert result["status"] == "confirmation_required"
    assert result["action"] == "browser.task"
    assert result["permission_level"] == "network"
    assert result["requires_confirmation"] is True
    assert result["dry_run"] is True
    assert result["plan"]["goal"] == "打开示例网站并截图"
    assert result["plan"]["start_url"] == "https://example.com"
    assert "agent-browser open https://example.com" in result["plan"]["command_plan"]
    assert "agent-browser screenshot" in result["plan"]["command_plan"]


def test_browser_open_url_rejects_non_http_urls():
    registry = create_default_action_registry()
    result = registry.execute(
        SkillActionRequest(
            action="browser.open_url",
            args={"url": "file:///C:/secret.txt"},
            confirmed=False,
        )
    )

    assert result["success"] is False
    assert result["status"] == "rejected"
    assert result["error"] == "Only http and https URLs are allowed."


def test_browser_task_rejects_non_http_start_url():
    registry = create_default_action_registry()
    result = registry.execute(
        SkillActionRequest(
            action="browser.task",
            args={"goal": "读取本地文件", "start_url": "file:///C:/secret.txt"},
            confirmed=False,
        )
    )

    assert result["success"] is False
    assert result["status"] == "rejected"
    assert result["error"] == "Only http and https start URLs are allowed."
