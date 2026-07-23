from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.multi_agent.contracts import (
    AgentResult,
    AgentStatus,
    AgentTask,
    Evidence,
)
from pmaa.multi_agent.runtime import AgentExecutionContext
from pmaa.schemas.task import Source
from pmaa.tools.factory import SearchTool


class WebResearchState(TypedDict, total=False):
    objective: str
    constraints: list[str]
    aspects: list[str]
    queries: list[str]
    executed_queries: list[str]
    sources: list[Source]
    gaps: list[str]
    sufficient: bool
    confidence: float
    rounds: int
    summary: str


class WebResearchAgent:
    agent_id = "web_research"
    system_prompt = (
        "你是 Web Research Agent，只负责从公开互联网收集实时、可信、可引用的信息。"
        "你需要拆分研究角度、生成查询、检查证据覆盖度，并明确证据不足之处。"
        "不得把搜索摘要当成已验证事实，不得执行浏览器交互或外部副作用。"
    )

    def __init__(
        self,
        search_tool: SearchTool,
        llm_client: LLMClient | None = None,
        *,
        max_rounds: int = 2,
        max_queries: int = 4,
        max_concurrency: int = 4,
    ) -> None:
        self.search_tool = search_tool
        self.llm_client = llm_client
        self.max_rounds = max_rounds
        self.max_queries = max_queries
        self.max_concurrency = max_concurrency
        self.graph = self._build_graph()

    def __call__(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        context.report_progress("analyzing_goal")
        state = self.graph.invoke(
            {
                "objective": task.objective,
                "constraints": task.constraints,
                "aspects": [],
                "queries": [],
                "executed_queries": [],
                "sources": [],
                "gaps": [],
                "sufficient": False,
                "confidence": 0,
                "rounds": 0,
                "summary": "",
            }
        )
        sources = state.get("sources", [])
        evidence = [
            Evidence(
                task_id=task.task_id,
                agent_id=self.agent_id,
                title=source.title,
                content=source.snippet,
                source="web",
                url=source.url,
                score=source.score,
                metadata={"query_count": len(state.get("executed_queries", []))},
            )
            for source in sources
        ]
        sufficient = bool(state.get("sufficient"))
        status = AgentStatus.COMPLETED if sufficient else AgentStatus.PARTIAL
        context.report_progress(
            "evidence_checked",
            source_count=len(sources),
            sufficient=sufficient,
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=status,
            summary=state.get("summary", ""),
            output={
                "aspects": state.get("aspects", []),
                "queries": state.get("executed_queries", []),
                "sources": [source.model_dump() for source in sources],
                "gaps": state.get("gaps", []),
                "sufficient": sufficient,
            },
            evidence=evidence,
            confidence=float(state.get("confidence", 0)),
            suggested_next_actions=(
                ["请 Supervisor 决定是否扩大检索范围。"] if not sufficient else []
            ),
        )

    def _build_graph(self):
        graph = StateGraph(WebResearchState)
        graph.add_node("analyze", self._analyze_goal)
        graph.add_node("search", self._search)
        graph.add_node("evaluate", self._evaluate)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "analyze")
        graph.add_edge("analyze", "search")
        graph.add_edge("search", "evaluate")
        graph.add_conditional_edges(
            "evaluate",
            self._next_after_evaluation,
            {"search": "search", "finalize": "finalize"},
        )
        graph.add_edge("finalize", END)
        return graph.compile()

    def _analyze_goal(self, state: WebResearchState) -> dict[str, Any]:
        objective = state["objective"]
        if self.llm_client is None:
            return {"aspects": [objective], "queries": [objective]}
        try:
            payload = self.llm_client.complete_json(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="system",
                        content=(
                            "只输出 JSON：{\"aspects\":[...],\"queries\":[...]}。"
                            f"最多生成 {self.max_queries} 个互补查询。"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            f"研究目标：{objective}\n"
                            f"约束：{state.get('constraints', [])}"
                        ),
                    ),
                ]
            )
            aspects = self._clean_strings(payload.get("aspects"))
            queries = self._clean_strings(payload.get("queries"))[: self.max_queries]
            return {
                "aspects": aspects or [objective],
                "queries": queries or [objective],
            }
        except (LLMClientError, ValueError, TypeError):
            return {"aspects": [objective], "queries": [objective]}

    def _search(self, state: WebResearchState) -> dict[str, Any]:
        executed = set(state.get("executed_queries", []))
        queries = [query for query in state.get("queries", []) if query not in executed]
        queries = queries[: self.max_queries]
        if not queries:
            return {"rounds": state.get("rounds", 0) + 1}

        workers = min(max(1, self.max_concurrency), len(queries))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            batches = list(executor.map(self._safe_search, queries))
        merged = self._deduplicate_sources(
            [*state.get("sources", []), *(item for batch in batches for item in batch)]
        )
        return {
            "sources": merged,
            "executed_queries": [*state.get("executed_queries", []), *queries],
            "rounds": state.get("rounds", 0) + 1,
        }

    def _evaluate(self, state: WebResearchState) -> dict[str, Any]:
        sources = state.get("sources", [])
        if self.llm_client is None:
            sufficient = len(sources) >= 2
            return {
                "sufficient": sufficient,
                "confidence": min(0.85, len(sources) / 4),
                "gaps": [] if sufficient else ["可用且互相独立的来源不足。"],
                "queries": [] if sufficient else [f"{state['objective']} 权威来源"],
            }
        evidence_preview = [
            {"title": item.title, "url": item.url, "snippet": item.snippet[:500]}
            for item in sources[:12]
        ]
        try:
            payload = self.llm_client.complete_json(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="system",
                        content=(
                            "检查证据的相关性、来源独立性、时效性和覆盖度。只输出 JSON："
                            "{\"sufficient\":true,\"confidence\":0.0,"
                            "\"gaps\":[...],\"additional_queries\":[...]}。"
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=f"目标：{state['objective']}\n证据：{evidence_preview}",
                    ),
                ]
            )
            sufficient = bool(payload.get("sufficient"))
            return {
                "sufficient": sufficient,
                "confidence": self._clamp_confidence(payload.get("confidence")),
                "gaps": self._clean_strings(payload.get("gaps")),
                "queries": self._clean_strings(payload.get("additional_queries"))[
                    : self.max_queries
                ],
            }
        except (LLMClientError, ValueError, TypeError):
            sufficient = len(sources) >= 2
            return {
                "sufficient": sufficient,
                "confidence": min(0.75, len(sources) / 4),
                "gaps": [] if sufficient else ["证据检查模型不可用且来源不足。"],
                "queries": [] if sufficient else [f"{state['objective']} 官方信息"],
            }

    def _next_after_evaluation(self, state: WebResearchState) -> str:
        if state.get("sufficient"):
            return "finalize"
        if state.get("rounds", 0) >= self.max_rounds:
            return "finalize"
        pending = set(state.get("queries", [])) - set(state.get("executed_queries", []))
        return "search" if pending else "finalize"

    def _finalize(self, state: WebResearchState) -> dict[str, Any]:
        source_count = len(state.get("sources", []))
        if state.get("sufficient"):
            summary = f"已完成互联网研究，共获得 {source_count} 个去重来源。"
        else:
            summary = f"互联网研究部分完成，共获得 {source_count} 个来源，仍存在证据缺口。"
        return {"summary": summary}

    def _safe_search(self, query: str) -> list[Source]:
        try:
            return self.search_tool(query)
        except Exception:
            return []

    @staticmethod
    def _deduplicate_sources(sources: list[Source]) -> list[Source]:
        deduplicated: dict[str, Source] = {}
        for source in sources:
            key = source.url.strip().lower() or source.title.strip().lower()
            if key and key not in deduplicated:
                deduplicated[key] = source
        return list(deduplicated.values())

    @staticmethod
    def _clean_strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            return max(0, min(1, float(value)))
        except (TypeError, ValueError):
            return 0
