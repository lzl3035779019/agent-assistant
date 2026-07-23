from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


NotificationKind = Literal["monitor", "daily_brief", "system"]
NotificationSeverity = Literal["info", "warning", "critical"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class NotificationRecord(BaseModel):
    notification_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: NotificationKind
    title: str
    content: str = ""
    severity: NotificationSeverity = "info"
    source_agent: str = ""
    related_rule_id: str | None = None
    read: bool = False
    created_at: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)
