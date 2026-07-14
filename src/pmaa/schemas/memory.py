from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


MemoryType = Literal["profile", "preference", "project", "instruction"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class MemoryCandidate(BaseModel):
    type: MemoryType
    content: str
    source: str = "user"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class MemoryValidation(BaseModel):
    should_save: bool
    reason: str


class MemoryRecord(BaseModel):
    memory_id: str = Field(default_factory=lambda: str(uuid4()))
    type: MemoryType
    content: str
    source: str = "user"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    last_used_at: str | None = None
    usage_count: int = 0
    enabled: bool = True
