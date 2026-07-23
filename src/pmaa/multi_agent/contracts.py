from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_DEPENDENCY = "waiting_dependency"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentMessageType(StrEnum):
    TASK_PROGRESS = "task_progress"
    DELEGATION_REQUEST = "delegation_request"
    RETRY_REQUEST = "retry_request"
    CLARIFICATION_REQUEST = "clarification_request"
    EVIDENCE = "evidence"
    CONFLICT = "conflict"
    ERROR = "error"


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    agent_id: str
    title: str = ""
    content: str
    source: str = ""
    url: str = ""
    score: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AgentTask(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    parent_task_id: str | None = None
    assigned_to: str
    objective: str
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    expected_output: str = ""
    depends_on: list[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=0, le=10)
    timeout_seconds: float = Field(default=90, gt=0)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=1, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_task(self) -> AgentTask:
        self.allowed_tools = list(dict.fromkeys(self.allowed_tools))
        self.depends_on = list(dict.fromkeys(self.depends_on))
        if self.task_id in self.depends_on:
            raise ValueError("A task cannot depend on itself.")
        if self.retry_count > self.max_retries:
            raise ValueError("retry_count cannot exceed max_retries.")
        return self


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    sender: str
    receiver: str = "supervisor"
    message_type: AgentMessageType
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AgentResult(BaseModel):
    task_id: str
    agent_id: str
    status: AgentStatus
    summary: str = ""
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    errors: list[str] = Field(default_factory=list)
    suggested_next_actions: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime = Field(default_factory=utc_now)


class AgentSpec(BaseModel):
    agent_id: str
    name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    enabled: bool = True
    max_retries: int = Field(default=1, ge=0)


class ToolRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    agent_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False


class ToolResult(BaseModel):
    request_id: str
    task_id: str
    agent_id: str
    tool_name: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class PendingAction(BaseModel):
    action_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    agent_id: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "medium"
    reason: str = ""


class ActionResult(BaseModel):
    action_id: str
    approved: bool
    executed: bool = False
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
