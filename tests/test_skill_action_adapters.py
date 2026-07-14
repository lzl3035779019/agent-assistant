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
