from pmaa.ui.action_audit import (
    append_action_audit,
    build_action_audit_entry,
    build_action_audit_markdown,
)


CONFIRMATION_RESULT = {
    "approved": True,
    "status": "executed",
    "message": "动作已执行。",
    "action": "browser.open_url",
    "tool_name": "skill:agent_browser",
    "skill_id": "agent_browser",
    "permission_level": "network",
    "plan": {"url": "https://www.baidu.com"},
    "confirmed_at": "2026-07-13T10:00:00+00:00",
    "execution": {
        "status": "executed",
        "url": "https://www.baidu.com",
    },
}


def test_build_action_audit_entry_keeps_structured_confirmation_fields():
    entry = build_action_audit_entry(CONFIRMATION_RESULT)

    assert entry == {
        "approved": True,
        "status": "executed",
        "action": "browser.open_url",
        "tool_name": "skill:agent_browser",
        "skill_id": "agent_browser",
        "permission_level": "network",
        "url": "https://www.baidu.com",
        "execution_status": "executed",
        "execution_reason": "",
        "confirmed_at": "2026-07-13T10:00:00+00:00",
    }


def test_build_action_audit_markdown_contains_clickable_target_url():
    markdown = build_action_audit_markdown(CONFIRMATION_RESULT)

    assert "动作已执行。" in markdown
    assert "**动作审计**" in markdown
    assert "- 动作：`browser.open_url`" in markdown
    assert "- 决策：允许" in markdown
    assert "- 目标 URL：[https://www.baidu.com](https://www.baidu.com)" in markdown


def test_append_action_audit_preserves_existing_entries():
    view = {"answer": "", "action_audit": [{"action": "old.action"}]}

    updated = append_action_audit(view, CONFIRMATION_RESULT)

    assert len(updated["action_audit"]) == 2
    assert updated["action_audit"][0]["action"] == "old.action"
    assert updated["action_audit"][1]["action"] == "browser.open_url"
