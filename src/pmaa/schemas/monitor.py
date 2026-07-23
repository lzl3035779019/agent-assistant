from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


MonitorTargetType = Literal[
    "company",
    "jobs",
    "news",
    "github",
    "tech_blog",
]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class MonitorRule(BaseModel):
    rule_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    target_type: MonitorTargetType
    target: str
    query: str
    enabled: bool = True
    interval_minutes: int = Field(default=360, ge=15, le=10080)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    last_run_at: str | None = None


class MonitorSnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    rule_id: str
    fingerprint: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    observed_at: str = Field(default_factory=utc_now_iso)
