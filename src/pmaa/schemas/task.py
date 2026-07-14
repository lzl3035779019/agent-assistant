from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanStep(BaseModel):
    step_id: str
    description: str
    agent: str
    expected_output: str


class ExecutionPlan(BaseModel):
    goal: str
    steps: list[PlanStep]
    required_agents: list[str] = Field(default_factory=list)
    expected_output: str = ""
    risk_points: list[str] = Field(default_factory=list)


class Source(BaseModel):
    title: str
    url: str
    snippet: str
    page_slug: str = ""
    document_title: str = ""
    document_filename: str = ""
    document_path: str = ""
    source_slug: str = ""
    import_id: str = ""
    chunk_id: int | None = None
    chunk_index: int | None = None
    score: float | None = None


class ReflectionResult(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    suggested_fix: str = ""
    need_retry: bool = False


class FinalResult(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    reflection: ReflectionResult


class AgentEvent(BaseModel):
    task_id: str
    agent: str
    event_type: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    user_input: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    result: FinalResult | None = None
