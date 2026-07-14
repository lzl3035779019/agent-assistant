from datetime import UTC, datetime
from typing import Any

from pmaa.skills.executors import ActionExecutorRegistry


def confirm_pending_action(
    pending_confirmation: dict[str, Any],
    *,
    approved: bool,
    executor_registry: ActionExecutorRegistry | None = None,
) -> dict[str, Any]:
    action = pending_confirmation.get("action", "")
    permission_level = pending_confirmation.get("permission_level", "")
    plan = pending_confirmation.get("plan", {})
    base = {
        "approved": approved,
        "action": action,
        "tool_name": pending_confirmation.get("tool_name", ""),
        "skill_id": pending_confirmation.get("skill_id", ""),
        "permission_level": permission_level,
        "plan": plan,
        "confirmed_at": datetime.now(UTC).isoformat(),
    }
    if not approved:
        return {
            **base,
            "status": "rejected_by_user",
            "message": "用户已拒绝该动作，未执行任何操作。",
            "execution": {
                "status": "cancelled",
                "reason": "User rejected the pending action.",
            },
        }
    if executor_registry is None:
        return {
            **base,
            "status": "approved_pending_executor",
            "message": "用户已批准该动作；真实执行器尚未配置，因此未执行外部操作。",
            "execution": {
                "status": "not_started",
                "reason": "Executor is not configured.",
            },
        }
    execution = executor_registry.execute(action, plan)
    if execution.get("status") == "executed":
        return {
            **base,
            "status": "executed",
            "message": "动作已执行。",
            "execution": execution,
        }
    return {
        **base,
        "status": "failed",
        "message": "动作执行失败。",
        "execution": execution,
    }
