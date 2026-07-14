from typing import Any


def build_action_audit_entry(confirmation_result: dict[str, Any]) -> dict[str, Any]:
    execution = confirmation_result.get("execution", {}) or {}
    plan = confirmation_result.get("plan", {}) or {}
    return {
        "approved": bool(confirmation_result.get("approved", False)),
        "status": confirmation_result.get("status", ""),
        "action": confirmation_result.get("action", ""),
        "tool_name": confirmation_result.get("tool_name", ""),
        "skill_id": confirmation_result.get("skill_id", ""),
        "permission_level": confirmation_result.get("permission_level", ""),
        "url": plan.get("url", ""),
        "execution_status": execution.get("status", ""),
        "execution_reason": execution.get("reason", ""),
        "confirmed_at": confirmation_result.get("confirmed_at", ""),
    }


def build_action_audit_markdown(confirmation_result: dict[str, Any]) -> str:
    entry = build_action_audit_entry(confirmation_result)
    message = str(confirmation_result.get("message", "")).strip()
    decision = "允许" if entry["approved"] else "拒绝"
    lines = [
        message or "动作确认已处理。",
        "",
        "**动作审计**",
        "",
        f"- 动作：`{entry['action']}`",
        f"- 决策：{decision}",
        f"- 执行状态：`{entry['execution_status'] or entry['status']}`",
    ]
    if entry["url"]:
        lines.append(f"- 目标 URL：[{entry['url']}]({entry['url']})")
    if entry["skill_id"]:
        lines.append(f"- Skill：`{entry['skill_id']}`")
    if entry["execution_reason"]:
        lines.append(f"- 说明：{entry['execution_reason']}")
    return "\n".join(lines)


def append_action_audit(
    view: dict[str, Any],
    confirmation_result: dict[str, Any],
) -> dict[str, Any]:
    audit_entries = [
        *(view.get("action_audit") or []),
        build_action_audit_entry(confirmation_result),
    ]
    return {
        **view,
        "action_audit": audit_entries,
    }
