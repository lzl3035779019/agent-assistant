from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any, Literal

from pydantic import BaseModel, Field

from pmaa.config import settings
from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.multi_agent.contracts import AgentTask
from pmaa.multi_agent.registry import AgentRegistry


logger = logging.getLogger(__name__)


SupervisorMode = Literal["direct_answer", "delegate", "tool", "clarification"]


class SupervisorDecision(BaseModel):
    intent: str = "unknown"
    mode: SupervisorMode = "clarification"
    tasks: list[AgentTask] = Field(default_factory=list)
    direct_tool: str = "none"
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    reason: str = ""


class SupervisorPlanError(ValueError):
    pass


class HierarchicalSupervisor:
    """Creates and validates child-agent assignments without a Policy Agent."""

    direct_tools = {"none", "knowledge", "wiki_get_page"}
    sensitive_tool_names = {"email.send", "smtp_send", "browser.execute"}

    def __init__(
        self,
        registry: AgentRegistry,
        llm_client: LLMClient | None = None,
        *,
        knowledge_available: bool | None = None,
        max_tasks: int = 8,
    ) -> None:
        self.registry = registry
        self.llm_client = llm_client
        self.knowledge_available = (
            settings.gbrain_mcp_enabled
            if knowledge_available is None
            else knowledge_available
        )
        self.max_tasks = max_tasks

    def analyze(
        self,
        user_input: str,
        conversation_context: str = "",
    ) -> SupervisorDecision:
        normalized = user_input.strip()
        if not normalized:
            return SupervisorDecision(
                intent="empty_input",
                mode="clarification",
                confidence=1,
                reason="用户输入为空。",
            )
        if self._is_model_identity_question(normalized.lower()):
            return SupervisorDecision(
                intent="model_identity",
                mode="direct_answer",
                confidence=1,
                reason="用户询问当前系统模型信息。",
            )

        fallback_reason = ""
        if self.llm_client is not None:
            try:
                decision = self._analyze_with_llm(normalized, conversation_context)
                return self.validate_decision(decision)
            except LLMClientError as exc:
                logger.warning("Supervisor LLM call failed: %s", exc)
                fallback_reason = "LLM 调用失败，已使用确定性降级路由。"
            except (KeyError, ValueError, SupervisorPlanError) as exc:
                logger.warning("Supervisor LLM decision rejected: %s", exc)
                fallback_reason = "LLM 路由结果未通过结构校验，已使用确定性降级路由。"
        else:
            fallback_reason = "LLM 未配置，已使用确定性降级路由。"

        fallback = self.validate_decision(self._fallback_decision(normalized))
        return fallback.model_copy(update={"reason": fallback_reason or fallback.reason})

    def validate_decision(self, decision: SupervisorDecision) -> SupervisorDecision:
        if len(decision.tasks) > self.max_tasks:
            raise SupervisorPlanError(
                f"Supervisor produced too many tasks: {len(decision.tasks)}"
            )
        if decision.direct_tool not in self.direct_tools:
            raise SupervisorPlanError(f"Unsupported Supervisor tool: {decision.direct_tool}")

        if decision.mode == "delegate" and not decision.tasks:
            raise SupervisorPlanError("Delegate mode requires at least one child task.")
        if decision.mode != "delegate" and decision.tasks:
            raise SupervisorPlanError(
                f"Mode {decision.mode} cannot contain child-agent tasks."
            )
        if decision.mode == "tool" and decision.direct_tool == "none":
            raise SupervisorPlanError("Tool mode requires a direct Supervisor tool.")
        if decision.mode != "tool" and decision.direct_tool != "none":
            raise SupervisorPlanError(
                f"Mode {decision.mode} cannot invoke a direct Supervisor tool."
            )
        if decision.direct_tool in {"knowledge", "wiki_get_page"} and not self.knowledge_available:
            raise SupervisorPlanError("GBrain knowledge tools are not available.")

        task_ids: set[str] = set()
        validated_tasks: list[AgentTask] = []
        for task in decision.tasks:
            if task.task_id in task_ids:
                raise SupervisorPlanError(f"Duplicate task ID: {task.task_id}")
            task_ids.add(task.task_id)
            spec = self.registry.validate_task(task)
            validated_tasks.append(
                task.model_copy(update={"max_retries": spec.max_retries})
            )

        for task in validated_tasks:
            unknown = set(task.depends_on) - task_ids
            if unknown:
                names = ", ".join(sorted(unknown))
                raise SupervisorPlanError(
                    f"Task {task.task_id} has unknown dependencies: {names}"
                )
        self._validate_acyclic(validated_tasks)

        sensitive = any(
            tool in self.sensitive_tool_names
            for task in validated_tasks
            for tool in task.allowed_tools
        ) or decision.intent in {"email_send", "external_action"}
        if sensitive and not decision.requires_confirmation:
            decision = decision.model_copy(update={"requires_confirmation": True})
        return decision.model_copy(update={"tasks": validated_tasks})

    def direct_answer(self, user_input: str, intent: str) -> str:
        if intent == "model_identity":
            return (
                "我是 PMAA 层级式多 Agent 助手。"
                f"当前配置模型为 `{settings.llm_model}`，提供方为 "
                f"`{settings.llm_provider}`。"
            )
        if self.llm_client is None:
            return "当前没有可用的 LLM，无法生成直接回答。"
        return self.llm_client.complete_text(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "你是 PMAA 的 Supervisor。当前请求不需要子 Agent 或外部工具，"
                        "请直接用中文完成请求。不要虚构工具执行结果。"
                    ),
                ),
                LLMMessage(role="user", content=user_input),
            ]
        )

    def _analyze_with_llm(
        self,
        user_input: str,
        conversation_context: str,
    ) -> SupervisorDecision:
        catalog = [
            {
                "agent_id": spec.agent_id,
                "description": spec.description,
                "capabilities": spec.capabilities,
                "allowed_tools": spec.allowed_tools,
                "max_retries": spec.max_retries,
            }
            for spec in self.registry.list_specs()
        ]
        payload = self.llm_client.complete_json(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "你是层级式多 Agent 系统中唯一的 Supervisor。只输出 JSON。"
                        "你负责理解目标、决定直接回答/调用知识工具/委派子 Agent/澄清，"
                        "并创建结构化 AgentTask。不要使用不存在的 Agent 或工具。"
                        "子 Agent 之间不能直接通信；有依赖时用 depends_on。"
                        "可相互独立的研究任务可以拆成多个任务并行执行。"
                        "本地 GBrain 知识检索不是 Agent；需要本地知识时设置 "
                        "mode=tool, direct_tool=knowledge。"
                        "发送邮件或其他外部副作用必须 requires_confirmation=true。"
                    ),
                ),
                LLMMessage(
                    role="system",
                    content=(
                        "JSON 字段：intent, mode, tasks, direct_tool, tool_arguments, "
                        "requires_confirmation, confidence, reason。"
                        "mode 只能是 direct_answer, delegate, tool, clarification。"
                        "tasks 中每项字段：task_id, parent_task_id, assigned_to, objective, "
                        "context, constraints, allowed_tools, expected_output, depends_on, "
                        "priority, timeout_seconds, retry_count, max_retries。"
                        "context 和 tool_arguments 必须是 JSON 对象；constraints、allowed_tools、"
                        "depends_on 必须是数组；priority 必须是 0 到 10 的整数。"
                        "无值时使用空对象、空数组或 direct_tool=none，不要输出 null。"
                    ),
                ),
                LLMMessage(role="system", content=f"Agent Catalog: {catalog}"),
                LLMMessage(
                    role="system",
                    content=(
                        "判断当前输入是否真正依赖历史上下文。只有无法独立理解的指代、"
                        "省略或继续请求才使用历史，完整的新任务不能因存在历史而变成追问。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"历史上下文：\n{conversation_context.strip() or '无'}\n\n"
                        f"当前输入：\n{user_input}"
                    ),
                ),
            ]
        )
        return SupervisorDecision.model_validate(self._normalize_llm_payload(payload))

    @staticmethod
    def _normalize_llm_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["tasks"] = normalized.get("tasks") or []
        normalized["direct_tool"] = normalized.get("direct_tool") or "none"
        normalized["tool_arguments"] = normalized.get("tool_arguments") or {}

        normalized_tasks: list[dict[str, Any]] = []
        for raw_task in normalized["tasks"]:
            if not isinstance(raw_task, dict):
                raise SupervisorPlanError("Each task must be a JSON object.")
            task = dict(raw_task)
            for field_name in ("task_id", "parent_task_id"):
                value = task.get(field_name)
                if value is not None:
                    task[field_name] = str(value)
            context = task.get("context")
            if context is None:
                task["context"] = {}
            elif isinstance(context, str):
                task["context"] = {"request_context": context}
            elif not isinstance(context, dict):
                raise SupervisorPlanError("Task context must be an object.")

            for field_name in ("constraints", "allowed_tools", "depends_on"):
                value = task.get(field_name)
                if value is None:
                    task[field_name] = []
                elif isinstance(value, str):
                    task[field_name] = [value] if value.strip() else []
                elif not isinstance(value, list):
                    raise SupervisorPlanError(f"Task {field_name} must be an array.")
            task["depends_on"] = [str(value) for value in task["depends_on"]]

            priority = task.get("priority")
            if isinstance(priority, str) and not priority.strip().isdigit():
                task["priority"] = {
                    "low": 2,
                    "normal": 5,
                    "medium": 5,
                    "high": 8,
                    "urgent": 10,
                }.get(priority.strip().lower(), 5)
            normalized_tasks.append(task)
        normalized["tasks"] = normalized_tasks
        return normalized

    def _fallback_decision(self, user_input: str) -> SupervisorDecision:
        text = user_input.lower()
        if self.knowledge_available and any(
            marker in text
            for marker in ["知识库", "gbrain", "wiki", "我的文档", "本地资料"]
        ):
            return SupervisorDecision(
                intent="knowledge_query",
                mode="tool",
                direct_tool="knowledge",
                tool_arguments={"query": user_input},
                confidence=0.9,
                reason="用户明确请求检索本地知识库。",
            )

        routes: list[tuple[list[str], str, str, list[str]]] = [
            (
                ["每日简报", "今日简报", "个人简报", "daily brief"],
                "daily_brief",
                "daily_brief",
                [],
            ),
            (
                ["邮件", "邮箱", "email", "mail", "收件箱"],
                "email",
                "email_task",
                ["email.list", "email.read", "email.draft"],
            ),
            (
                ["监控", "追踪", "订阅", "github更新", "公司动态"],
                "information_monitor",
                "monitoring",
                ["monitor.store", "rss.read", "github.read"],
            ),
            (
                ["记住", "长期记忆", "我的偏好", "忘记"],
                "memory",
                "memory_management",
                ["memory.read", "memory.write"],
            ),
            (
                ["最新", "今天", "实时", "新闻", "联网", "搜索", "查一下", "research"],
                "web_research",
                "web_research",
                ["web_search"],
            ),
        ]
        for markers, agent_id, intent, tools in routes:
            if any(marker in text for marker in markers):
                return SupervisorDecision(
                    intent=intent,
                    mode="delegate",
                    tasks=[
                        AgentTask(
                            assigned_to=agent_id,
                            objective=user_input,
                            allowed_tools=tools,
                            expected_output="结构化结果、证据和置信度",
                        )
                    ],
                    requires_confirmation=intent == "email_task" and any(
                        marker in text for marker in ["发送", "发邮件", "send"]
                    ),
                    confidence=0.72,
                    reason="LLM 不可用，使用保守的确定性降级路由。",
                )
        return SupervisorDecision(
            intent="general_request",
            mode="direct_answer",
            confidence=0.55,
            reason="未发现必须使用子 Agent 或外部工具的证据。",
        )

    @staticmethod
    def _validate_acyclic(tasks: list[AgentTask]) -> None:
        indegree = {task.task_id: len(task.depends_on) for task in tasks}
        dependents: dict[str, list[str]] = defaultdict(list)
        for task in tasks:
            for dependency in task.depends_on:
                dependents[dependency].append(task.task_id)
        queue = deque(task_id for task_id, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for dependent in dependents[current]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)
        if visited != len(tasks):
            raise SupervisorPlanError("Supervisor task plan contains a dependency cycle.")

    @staticmethod
    def _is_model_identity_question(text: str) -> bool:
        return any(
            marker in text
            for marker in [
                "你是什么模型",
                "你是啥模型",
                "当前模型",
                "what model are you",
                "which model",
            ]
        )
