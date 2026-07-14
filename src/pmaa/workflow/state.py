from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from pmaa.schemas.memory import MemoryRecord
from pmaa.schemas.skill import SkillRecord
from pmaa.schemas.task import AgentEvent, ExecutionPlan, FinalResult, ReflectionResult, Source


class WorkflowGraphState(TypedDict, total=False):
    task_id: str
    user_input: str
    conversation_context: str
    base_conversation_context: str
    retrieved_memories: list[MemoryRecord]
    loaded_skills: list[SkillRecord]
    intent: str
    task_kind: str
    execution_mode: str
    required_tool: str
    should_plan: bool
    route_confidence: float
    direct_answer: str
    plan: ExecutionPlan
    tool_request: dict[str, str]
    tool_result: dict
    pending_confirmation: dict
    sources: list[Source]
    draft_answer: str
    reflection: ReflectionResult
    final_result: FinalResult
    events: list[AgentEvent]


class WorkflowResult(BaseModel):
    task_id: str = ""
    user_input: str
    conversation_context: str = ""
    plan: ExecutionPlan | None = None
    sources: list[Source] = Field(default_factory=list)
    tool_result: dict = Field(default_factory=dict)
    pending_confirmation: dict = Field(default_factory=dict)
    draft_answer: str = ""
    final_result: FinalResult | None = None
    events: list[AgentEvent] = Field(default_factory=list)
