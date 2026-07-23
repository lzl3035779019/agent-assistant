from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.config import load_settings
from pmaa.multi_agent.contracts import AgentResult, AgentStatus, AgentTask
from pmaa.multi_agent.runtime import AgentExecutionContext


DEPENDENCY_REQUESTS = {
    "email": ("email.today_unread", "汇总当天未读和重要邮件"),
    "news": ("web_research", "获取当天重要热点信息"),
    "memory": ("memory.retrieve", "获取用户关注领域和简报偏好"),
    "calendar": ("calendar.read", "获取今日日程"),
}

TOPIC_REQUEST = (
    "interest_topics.read",
    "读取用户选择的简报关注主题",
)


class DailyBriefState(TypedDict, total=False):
    objective: str
    current_date: str
    execution_context: AgentExecutionContext
    dependencies: dict[str, Any]
    normalized: dict[str, Any]
    priorities: dict[str, Any]
    missing_sources: list[str]
    requested_capabilities: list[str]
    waiting: bool
    brief: str
    quality_passed: bool
    quality_issues: list[str]
    revision_count: int
    error: str


class DailyBriefGraphAgent:
    agent_id = "daily_brief"
    system_prompt = (
        "你是 Daily Brief Agent。你将当天邮件、热点信息、日程和用户偏好整理为个人简报。"
        "只保留与用户相关、可验证且可行动的信息；明确缺失的数据源，绝不补写不存在的"
        "邮件、新闻或日程。"
    )

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        max_revisions: int = 1,
    ) -> None:
        self.llm_client = llm_client
        self.max_revisions = max_revisions
        self.graph = self._build_graph()

    def __call__(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        dependencies = task.context.get("dependency_results")
        if not isinstance(dependencies, dict) or not dependencies:
            dependencies = self._dependency_results(task, context)
        state = self.graph.invoke(
            {
                "objective": task.objective,
                "current_date": str(task.context.get("current_date") or _today()),
                "execution_context": context,
                "dependencies": dependencies if isinstance(dependencies, dict) else {},
                "normalized": {},
                "priorities": {},
                "missing_sources": [],
                "requested_capabilities": [],
                "waiting": False,
                "brief": "",
                "quality_passed": False,
                "quality_issues": [],
                "revision_count": 0,
                "error": "",
            }
        )
        if state.get("waiting"):
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=AgentStatus.WAITING_DEPENDENCY,
                summary="已向 Supervisor 请求简报依赖数据。",
                output={
                    "requested_capabilities": state.get("requested_capabilities", []),
                    "workflow": ["collect_dependencies"],
                },
                confidence=0.8,
            )
        error = state.get("error", "")
        if error:
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=AgentStatus.FAILED,
                summary="每日简报生成失败。",
                output={"workflow": self._completed_workflow(state)},
                errors=[error],
                confidence=0.2,
            )
        missing = state.get("missing_sources", [])
        quality_passed = bool(state.get("quality_passed"))
        partial = bool(missing) or not quality_passed
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=AgentStatus.PARTIAL if partial else AgentStatus.COMPLETED,
            summary="每日个人简报已生成。",
            output={
                "brief": state.get("brief", ""),
                "missing_sources": missing,
                "priorities": state.get("priorities", {}),
                "quality": {
                    "passed": quality_passed,
                    "issues": state.get("quality_issues", []),
                    "revision_count": state.get("revision_count", 0),
                },
                "workflow": self._completed_workflow(state),
            },
            confidence=0.72 if partial else 0.9,
            suggested_next_actions=(
                ["补充缺失数据源后可重新生成完整简报。"] if missing else []
            ),
        )

    def _build_graph(self):
        graph = StateGraph(DailyBriefState)
        graph.add_node("collect", self._collect)
        graph.add_node("normalize", self._normalize)
        graph.add_node("prioritize", self._prioritize)
        graph.add_node("compose", self._compose)
        graph.add_node("quality", self._quality_check)
        graph.add_node("revise", self._revise)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "collect")
        graph.add_conditional_edges(
            "collect",
            self._after_collect,
            {"wait": END, "normalize": "normalize"},
        )
        graph.add_edge("normalize", "prioritize")
        graph.add_edge("prioritize", "compose")
        graph.add_edge("compose", "quality")
        graph.add_conditional_edges(
            "quality",
            self._after_quality,
            {"revise": "revise", "finalize": "finalize"},
        )
        graph.add_edge("revise", "quality")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _collect(self, state: DailyBriefState) -> dict[str, Any]:
        context = state["execution_context"]
        context.report_progress("collecting_brief_dependencies")
        dependencies = self._canonical_dependencies(state.get("dependencies", {}))
        if all(name in dependencies for name in DEPENDENCY_REQUESTS):
            missing = [
                name
                for name in DEPENDENCY_REQUESTS
                if self._dependency_missing(dependencies.get(name))
            ]
            return {
                "waiting": False,
                "dependencies": dependencies,
                "missing_sources": missing,
            }
        if not dependencies:
            requested: list[str] = []
            initial_requests = [
                TOPIC_REQUEST,
                DEPENDENCY_REQUESTS["email"],
                DEPENDENCY_REQUESTS["memory"],
                DEPENDENCY_REQUESTS["calendar"],
            ]
            for capability, objective in initial_requests:
                context.request_delegation(
                    target_capability=capability,
                    objective=objective,
                    reason="生成个性化每日简报需要该数据。",
                )
                requested.append(capability)
            return {
                "waiting": True,
                "requested_capabilities": requested,
                "dependencies": {},
            }
        if "news" not in dependencies:
            capability, _ = DEPENDENCY_REQUESTS["news"]
            objective = self._news_objective(dependencies.get("topics"))
            context.request_delegation(
                target_capability=capability,
                objective=objective,
                reason="根据用户选择的关注主题获取当天热点信息。",
                context={"interest_topics": dependencies.get("topics", {})},
            )
            return {
                "waiting": True,
                "requested_capabilities": [capability],
                "dependencies": dependencies,
            }
        missing = [
            name
            for name in DEPENDENCY_REQUESTS
            if self._dependency_missing(dependencies.get(name))
        ]
        return {
            "waiting": False,
            "dependencies": dependencies,
            "missing_sources": missing,
        }

    @staticmethod
    def _after_collect(state: DailyBriefState) -> str:
        return "wait" if state.get("waiting") else "normalize"

    @staticmethod
    def _normalize(state: DailyBriefState) -> dict[str, Any]:
        state["execution_context"].report_progress("normalizing_brief_inputs")
        dependencies = state.get("dependencies", {})
        email_data = dependencies.get("email") or {}
        news_data = dependencies.get("news") or {}
        memory_data = dependencies.get("memory") or {}
        calendar_data = dependencies.get("calendar") or {}
        topic_data = dependencies.get("topics") or {}
        normalized = {
            "emails": email_data.get("messages", []) if isinstance(email_data, dict) else [],
            "email_analysis": (
                email_data.get("analysis", {}) if isinstance(email_data, dict) else {}
            ),
            "news": news_data.get("sources", []) if isinstance(news_data, dict) else [],
            "memories": (
                memory_data.get("memories", []) if isinstance(memory_data, dict) else []
            ),
            "calendar": (
                calendar_data.get("events", []) if isinstance(calendar_data, dict) else []
            ),
            "topics": (
                topic_data.get("topics", []) if isinstance(topic_data, dict) else []
            ),
        }
        return {"normalized": normalized}

    def _prioritize(self, state: DailyBriefState) -> dict[str, Any]:
        state["execution_context"].report_progress("prioritizing_brief_items")
        normalized = state.get("normalized", {})
        fallback = self._fallback_priorities(normalized)
        if self.llm_client is None:
            return {"priorities": fallback}
        try:
            payload = self.llm_client.complete_json(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="system",
                        content=(
                            "根据紧迫性、用户相关性和可行动性排序。只输出 JSON："
                            "{\"top_actions\":[...],\"important_emails\":[...],"
                            "\"schedule\":[...],\"headlines\":[...]}。"
                        ),
                    ),
                    LLMMessage(role="user", content=f"简报数据：{normalized}"),
                ]
            )
            if isinstance(payload, dict) and any(
                key in payload
                for key in {"top_actions", "important_emails", "schedule", "headlines"}
            ):
                return {"priorities": payload}
        except (LLMClientError, ValueError, TypeError):
            pass
        return {"priorities": fallback}

    def _compose(self, state: DailyBriefState) -> dict[str, Any]:
        state["execution_context"].report_progress("composing_daily_brief")
        fallback = self._fallback_brief(
            state.get("objective", ""),
            state.get("priorities", {}),
            state.get("missing_sources", []),
            state.get("current_date", ""),
        )
        if self.llm_client is None:
            return {"brief": fallback}
        try:
            brief = self.llm_client.complete_text(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="user",
                        content=(
                            f"目标：{state.get('objective', '')}\n"
                            f"当前日期：{state.get('current_date', '')}\n"
                            f"已排序信息：{state.get('priorities', {})}\n"
                            f"缺失数据源：{state.get('missing_sources', [])}\n"
                            "生成简洁的中文 Markdown 简报，包含今日重点、邮件、日程、"
                            "值得关注和建议行动。缺失项必须明确说明。"
                        ),
                    ),
                ]
            )
            normalized_brief = self._normalize_brief_date(
                brief.strip(),
                state.get("current_date", ""),
            )
            return {"brief": normalized_brief or fallback}
        except LLMClientError:
            return {"brief": fallback}

    def _quality_check(self, state: DailyBriefState) -> dict[str, Any]:
        state["execution_context"].report_progress("checking_brief_quality")
        brief = state.get("brief", "").strip()
        missing = state.get("missing_sources", [])
        issues: list[str] = []
        if len(brief) < 30:
            issues.append("简报内容过短。")
        if missing and "缺失" not in brief and "暂不可用" not in brief:
            issues.append("未披露缺失数据源。")
        if issues or self.llm_client is None:
            return {"quality_passed": not issues, "quality_issues": issues}
        try:
            payload = self.llm_client.complete_json(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="system",
                        content=(
                            "检查简报是否忠于输入、可行动、无虚构且披露缺失项。"
                            "只输出 JSON：{\"passed\":true,\"issues\":[...]}。"
                        ),
                    ),
                    LLMMessage(role="user", content=brief),
                ]
            )
            raw_issues = payload.get("issues", [])
            model_issues = raw_issues if isinstance(raw_issues, list) else []
            return {
                "quality_passed": bool(payload.get("passed")) and not model_issues,
                "quality_issues": [str(item) for item in model_issues],
            }
        except (LLMClientError, ValueError, TypeError):
            return {"quality_passed": True, "quality_issues": []}

    def _after_quality(self, state: DailyBriefState) -> str:
        if state.get("quality_passed"):
            return "finalize"
        if state.get("revision_count", 0) >= self.max_revisions:
            return "finalize"
        return "revise"

    def _revise(self, state: DailyBriefState) -> dict[str, Any]:
        state["execution_context"].report_progress("revising_daily_brief")
        missing = state.get("missing_sources", [])
        issues = state.get("quality_issues", [])
        brief = state.get("brief", "")
        revised = brief
        if self.llm_client is not None:
            try:
                revised = self.llm_client.complete_text(
                    [
                        LLMMessage(role="system", content=self.system_prompt),
                        LLMMessage(
                            role="user",
                            content=(
                                f"原简报：\n{brief}\n\n问题：{issues}\n"
                                f"当前日期：{state.get('current_date', '')}\n"
                                f"缺失数据源：{missing}\n请修订，不得添加新事实。"
                            ),
                        ),
                    ]
                ).strip()
            except LLMClientError:
                revised = brief
        if missing and "缺失" not in revised and "暂不可用" not in revised:
            revised = (
                f"{revised}\n\n> 数据缺失：{', '.join(missing)} 暂不可用，"
                "相关内容未纳入本次简报。"
            ).strip()
        return {
            "brief": revised,
            "revision_count": state.get("revision_count", 0) + 1,
        }

    @staticmethod
    def _finalize(state: DailyBriefState) -> dict[str, Any]:
        return {}

    @staticmethod
    def _dependency_results(
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> dict[str, Any]:
        snapshot = context.blackboard.snapshot()
        results: dict[str, Any] = dict(snapshot.artifacts.get(task.task_id, {}))
        for child_id, child_task in snapshot.tasks.items():
            if child_task.parent_task_id != task.task_id:
                continue
            child_result = snapshot.results.get(child_id)
            if child_result is not None:
                results[child_task.assigned_to] = child_result.output
        return results

    @staticmethod
    def _canonical_dependencies(dependencies: dict[str, Any]) -> dict[str, Any]:
        aliases = {
            "email": "email",
            "email.today_unread": "email",
            "web_research": "news",
            "news": "news",
            "memory": "memory",
            "memory.retrieve": "memory",
            "calendar": "calendar",
            "calendar.read": "calendar",
            "topics": "topics",
            "interest_topics.read": "topics",
        }
        canonical: dict[str, Any] = {}
        for name, value in dependencies.items():
            target = aliases.get(name)
            if target:
                canonical[target] = value
        return canonical

    @staticmethod
    def _news_objective(topic_data: Any) -> str:
        topics = topic_data.get("topics", []) if isinstance(topic_data, dict) else []
        topic_names = [
            str(topic.get("name", "")).strip()
            for topic in topics
            if isinstance(topic, dict) and str(topic.get("name", "")).strip()
        ]
        topic_queries = [
            str(topic.get("query", "")).strip()
            for topic in topics
            if isinstance(topic, dict) and str(topic.get("query", "")).strip()
        ]
        if not topic_queries:
            return DEPENDENCY_REQUESTS["news"][1]
        return (
            f"获取今天与以下关注主题相关的热点信息：{'、'.join(topic_names)}。"
            f"检索重点：{'；'.join(topic_queries)}"
        )

    @staticmethod
    def _dependency_missing(value: Any) -> bool:
        if not value:
            return True
        if isinstance(value, dict):
            return value.get("status") in {
                "failed",
                "unavailable",
                "configuration_error",
            }
        return False

    @staticmethod
    def _fallback_priorities(normalized: dict[str, Any]) -> dict[str, Any]:
        emails = normalized.get("emails", [])
        analysis = normalized.get("email_analysis", {})
        analyzed_messages = analysis.get("messages", []) if isinstance(analysis, dict) else []
        important_ids = {
            item.get("message_id")
            for item in analyzed_messages
            if isinstance(item, dict) and item.get("priority") == "high"
        }
        important_emails = [
            item
            for item in emails
            if isinstance(item, dict)
            and (item.get("message_id") in important_ids or item.get("unread"))
        ]
        calendar = normalized.get("calendar", [])
        news = normalized.get("news", [])
        top_actions = [
            f"处理邮件：{item.get('subject', '无主题')}"
            for item in important_emails[:3]
        ]
        top_actions.extend(
            f"参加日程：{item.get('title', '未命名日程')}"
            for item in calendar[:3]
            if isinstance(item, dict)
        )
        return {
            "top_actions": top_actions,
            "important_emails": important_emails[:5],
            "schedule": calendar[:5],
            "headlines": news[:5],
            "preferences": normalized.get("memories", [])[:5],
        }

    @staticmethod
    def _fallback_brief(
        objective: str,
        priorities: dict[str, Any],
        missing: list[str],
        current_date: str = "",
    ) -> str:
        def lines(items: Any, formatter) -> str:
            if not isinstance(items, list) or not items:
                return "- 暂无需要处理的内容。"
            return "\n".join(f"- {formatter(item)}" for item in items)

        actions = lines(priorities.get("top_actions"), lambda item: str(item))
        emails = lines(
            priorities.get("important_emails"),
            lambda item: (
                f"{item.get('subject', '无主题')}，来自 {item.get('from_addr', '未知发件人')}"
                if isinstance(item, dict)
                else str(item)
            ),
        )
        schedule = lines(
            priorities.get("schedule"),
            lambda item: (
                f"{item.get('title', '未命名日程')} {item.get('start', '')}".strip()
                if isinstance(item, dict)
                else str(item)
            ),
        )
        headlines = lines(
            priorities.get("headlines"),
            lambda item: item.get("title", str(item)) if isinstance(item, dict) else str(item),
        )
        brief = (
            f"# 今日个人简报\n\n生成日期：{current_date}\n\n目标：{objective}\n\n"
            f"## 今日重点\n\n{actions}\n\n"
            f"## 重要邮件\n\n{emails}\n\n"
            f"## 今日日程\n\n{schedule}\n\n"
            f"## 值得关注\n\n{headlines}"
        )
        if missing:
            brief += (
                f"\n\n> 数据缺失：{', '.join(missing)} 暂不可用，"
                "相关内容未纳入本次简报。"
            )
        return brief

    @staticmethod
    def _normalize_brief_date(brief: str, current_date: str) -> str:
        if not brief or not current_date:
            return brief
        return re.sub(
            r"(?m)(生成(?:时间|日期)\s*[*：:]*)\s*\d{4}-\d{1,2}-\d{1,2}",
            rf"\g<1>{current_date}",
            brief,
            count=1,
        )

    @staticmethod
    def _completed_workflow(state: DailyBriefState) -> list[str]:
        workflow = [
            "collect_dependencies",
            "normalize_inputs",
            "prioritize_items",
            "compose_brief",
            "quality_check",
        ]
        if state.get("revision_count", 0):
            workflow.extend(["revise_brief", "quality_check"])
        workflow.append("finalize")
        return workflow


# Compatibility alias for the previous adapter class name.
DailyBriefAgent = DailyBriefGraphAgent


def _today() -> str:
    timezone_name = load_settings().calendar_timezone
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().date().isoformat()
    return datetime.now(timezone).date().isoformat()
