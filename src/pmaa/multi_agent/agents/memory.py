from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from pmaa.agents.memory import MemoryAgent as LegacyMemoryAgent
from pmaa.multi_agent.contracts import AgentResult, AgentStatus, AgentTask
from pmaa.multi_agent.runtime import AgentExecutionContext
from pmaa.schemas.memory import MemoryCandidate, MemoryRecord, MemoryValidation


class MemoryAgentState(TypedDict, total=False):
    mode: str
    query: str
    limit: int
    user_input: str
    assistant_answer: str
    conversation_context: str
    allowed_tools: list[str]
    execution_context: AgentExecutionContext
    memories: list[MemoryRecord]
    candidates: list[MemoryCandidate]
    validations: list[MemoryValidation]
    approved: list[MemoryCandidate]
    saved: list[MemoryRecord]
    write_skipped: bool
    error: str


class MemoryGraphAgent:
    """Independent Memory Agent workflow backed by the existing memory domain service."""

    agent_id = "memory"
    system_prompt = (
        "你是 Memory Agent。你只维护用户长期记忆，区分稳定事实、偏好、长期指令"
        "与一次性请求；秘密、授权码、实时信息和模型推测永不写入。"
    )

    def __init__(self, memory: LegacyMemoryAgent) -> None:
        self.memory = memory
        self.graph = self._build_graph()

    def __call__(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        mode = str(task.context.get("mode", "retrieve"))
        state = self.graph.invoke(
            {
                "mode": mode,
                "query": str(task.context.get("query") or task.objective),
                "limit": int(task.context.get("limit", 5)),
                "user_input": str(task.context.get("user_input", "")),
                "assistant_answer": str(task.context.get("assistant_answer", "")),
                "conversation_context": str(
                    task.context.get("conversation_context", "")
                ),
                "allowed_tools": task.allowed_tools,
                "execution_context": context,
                "memories": [],
                "candidates": [],
                "validations": [],
                "approved": [],
                "saved": [],
                "write_skipped": False,
                "error": "",
            }
        )
        error = state.get("error", "")
        if error:
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=AgentStatus.FAILED,
                summary="Memory Agent 执行失败。",
                output={"mode": mode},
                errors=[error],
                confidence=0.1,
            )
        if mode == "retrieve":
            memories = state.get("memories", [])
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=AgentStatus.COMPLETED,
                summary=f"检索到 {len(memories)} 条相关长期记忆。",
                output={
                    "mode": mode,
                    "memories": [item.model_dump() for item in memories],
                    "workflow": ["retrieve"],
                },
                confidence=0.9 if memories else 0.6,
            )

        candidates = state.get("candidates", [])
        validations = state.get("validations", [])
        saved = state.get("saved", [])
        write_skipped = bool(state.get("write_skipped"))
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=AgentStatus.PARTIAL if write_skipped else AgentStatus.COMPLETED,
            summary=f"识别 {len(candidates)} 条候选记忆，保存 {len(saved)} 条。",
            output={
                "mode": mode,
                "candidates": [item.model_dump() for item in candidates],
                "validations": [item.model_dump() for item in validations],
                "saved": [item.model_dump() for item in saved],
                "write_skipped": write_skipped,
                "workflow": ["extract", "validate", "update"],
            },
            confidence=0.9,
            suggested_next_actions=(
                ["需要 memory.write 权限才能保存已通过校验的候选记忆。"]
                if write_skipped
                else []
            ),
        )

    def _build_graph(self):
        graph = StateGraph(MemoryAgentState)
        graph.add_node("route", self._route)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("extract", self._extract)
        graph.add_node("validate", self._validate)
        graph.add_node("update", self._update)
        graph.add_node("unsupported", self._unsupported)
        graph.add_edge(START, "route")
        graph.add_conditional_edges(
            "route",
            self._select_mode,
            {
                "retrieve": "retrieve",
                "consolidate": "extract",
                "unsupported": "unsupported",
            },
        )
        graph.add_edge("retrieve", END)
        graph.add_edge("extract", "validate")
        graph.add_edge("validate", "update")
        graph.add_edge("update", END)
        graph.add_edge("unsupported", END)
        return graph.compile()

    @staticmethod
    def _route(state: MemoryAgentState) -> dict[str, Any]:
        return {}

    @staticmethod
    def _select_mode(state: MemoryAgentState) -> str:
        mode = state.get("mode")
        return mode if mode in {"retrieve", "consolidate"} else "unsupported"

    def _retrieve(self, state: MemoryAgentState) -> dict[str, Any]:
        context = state["execution_context"]
        context.report_progress("retrieving")
        if "memory.read" not in state.get("allowed_tools", []):
            return {"error": "Memory retrieval requires memory.read permission."}
        records = self.memory.retrieve(state.get("query", ""), limit=state.get("limit", 5))
        return {"memories": records}

    def _extract(self, state: MemoryAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress("extracting_candidates")
        candidates = self.memory.consolidate(
            user_input=state.get("user_input", ""),
            assistant_answer=state.get("assistant_answer", ""),
            conversation_context=state.get("conversation_context", ""),
        )
        return {"candidates": candidates}

    def _validate(self, state: MemoryAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress("validating_candidates")
        candidates = state.get("candidates", [])
        validations = [self.memory.validate(candidate) for candidate in candidates]
        approved = [
            candidate
            for candidate, validation in zip(candidates, validations, strict=True)
            if validation.should_save
        ]
        return {"validations": validations, "approved": approved}

    def _update(self, state: MemoryAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress("updating_memory")
        approved = state.get("approved", [])
        if "memory.write" not in state.get("allowed_tools", []):
            return {"saved": [], "write_skipped": bool(approved)}
        return {"saved": self.memory.update(approved)}

    @staticmethod
    def _unsupported(state: MemoryAgentState) -> dict[str, Any]:
        return {"error": f"Unsupported memory mode: {state.get('mode', '')}"}


# Compatibility alias for code and historical tests that used the adapter name.
MemorySubAgent = MemoryGraphAgent
