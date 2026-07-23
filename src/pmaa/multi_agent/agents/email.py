from __future__ import annotations

from email.utils import parseaddr
from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from pmaa.agents.email import EmailAgent as LegacyEmailRouter
from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.multi_agent.contracts import AgentResult, AgentStatus, AgentTask
from pmaa.multi_agent.runtime import AgentExecutionContext
from pmaa.tools.email_tool import EmailTool


ACTION_PERMISSIONS = {
    "list_recent": "email.list",
    "count_unread": "email.list",
    "count_today_unread": "email.list",
    "get_message": "email.read",
    "draft_reply": "email.draft",
    "prepare_send": "email.draft",
}


class EmailAgentState(TypedDict, total=False):
    objective: str
    request: dict[str, Any]
    action: str
    allowed_tools: list[str]
    execution_context: AgentExecutionContext
    authorized: bool
    required_permission: str
    tool_result: dict[str, Any]
    analysis: dict[str, Any]
    risk_flags: list[str]
    error: str


class EmailGraphAgent:
    """Read-only/draft Email Agent. Sending is delegated to Action Executor."""

    agent_id = "email"
    system_prompt = (
        "你是 Email Agent。你负责理解邮件任务、读取与分类邮件、判断优先级和起草回复。"
        "你不得发送邮件；涉及发送时只能生成经过校验的待确认动作。"
        "不得在输出中暴露邮箱授权码或其他秘密。"
    )

    def __init__(
        self,
        email_tool: EmailTool,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.email_tool = email_tool
        self.llm_client = llm_client
        self.router = LegacyEmailRouter()
        self.graph = self._build_graph()

    def __call__(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        raw_request = task.context.get("email_request")
        state = self.graph.invoke(
            {
                "objective": task.objective,
                "request": dict(raw_request) if isinstance(raw_request, dict) else {},
                "action": "",
                "allowed_tools": task.allowed_tools,
                "execution_context": context,
                "authorized": False,
                "required_permission": "",
                "tool_result": {},
                "analysis": {},
                "risk_flags": [],
                "error": "",
            }
        )
        action = state.get("action", "")
        tool_result = state.get("tool_result", {})
        error = state.get("error", "")
        workflow = ["understand", "authorize"]
        if state.get("authorized"):
            workflow.extend(["execute", "inspect"])
            if tool_result.get("status") == "confirmation_required":
                workflow.append("validate_send_plan")
            elif action in {"list_recent", "get_message", "draft_reply"}:
                workflow.append("analyze")
        if error:
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=AgentStatus.FAILED,
                summary="邮件任务未通过执行校验。",
                output={
                    "action": action,
                    "workflow": workflow,
                    "risk_flags": state.get("risk_flags", []),
                },
                errors=[error],
                confidence=0.2,
            )
        if tool_result.get("status") == "confirmation_required":
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=AgentStatus.WAITING_CONFIRMATION,
                summary="邮件发送计划已生成并通过校验，等待用户确认。",
                output={
                    "action": action,
                    "pending_action": tool_result,
                    "analysis": state.get("analysis", {}),
                    "risk_flags": state.get("risk_flags", []),
                    "workflow": workflow,
                },
                confidence=0.95,
            )
        failed = tool_result.get("status") in {
            "configuration_error",
            "failed",
            "unsupported",
        }
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=AgentStatus.FAILED if failed else AgentStatus.COMPLETED,
            summary=str(tool_result.get("answer", "邮件任务已处理。")),
            output={
                **tool_result,
                "action": action,
                "analysis": state.get("analysis", {}),
                "risk_flags": state.get("risk_flags", []),
                "workflow": workflow,
            },
            confidence=0.9 if not failed else 0.2,
            errors=[str(tool_result.get("answer", "Email tool failed."))] if failed else [],
        )

    def _build_graph(self):
        graph = StateGraph(EmailAgentState)
        graph.add_node("understand", self._understand)
        graph.add_node("authorize", self._authorize)
        graph.add_node("execute", self._execute)
        graph.add_node("inspect", self._inspect)
        graph.add_node("analyze", self._analyze)
        graph.add_node("validate_send", self._validate_send)
        graph.add_node("finish", self._finish)
        graph.add_edge(START, "understand")
        graph.add_edge("understand", "authorize")
        graph.add_conditional_edges(
            "authorize",
            self._after_authorize,
            {"execute": "execute", "finish": "finish"},
        )
        graph.add_edge("execute", "inspect")
        graph.add_conditional_edges(
            "inspect",
            self._after_inspect,
            {
                "analyze": "analyze",
                "validate_send": "validate_send",
                "finish": "finish",
            },
        )
        graph.add_edge("analyze", "finish")
        graph.add_edge("validate_send", "finish")
        graph.add_edge("finish", END)
        return graph.compile()

    def _understand(self, state: EmailAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress("understanding_email_request")
        request = state.get("request", {})
        if not request:
            request = self._request_from_objective(state.get("objective", ""))
        action = str(request.get("action", "list_recent"))
        return {"request": request, "action": action}

    def _request_from_objective(self, objective: str) -> dict[str, Any]:
        fallback = self.router.build_tool_request(objective)
        if self.llm_client is None:
            return fallback
        try:
            payload = self.llm_client.complete_json(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="system",
                        content=(
                            "将任务转换为邮件工具请求。只输出 JSON，action 只能是 "
                            "list_recent、count_unread、count_today_unread、get_message、"
                            "draft_reply、prepare_send；不得输出 send。"
                        ),
                    ),
                    LLMMessage(role="user", content=objective),
                ]
            )
        except (LLMClientError, ValueError, TypeError):
            return fallback
        action = str(payload.get("action", ""))
        if action not in ACTION_PERMISSIONS:
            return fallback
        return {**fallback, **payload, "action": action}

    @staticmethod
    def _authorize(state: EmailAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress("checking_email_permission")
        action = state.get("action", "")
        required = ACTION_PERMISSIONS.get(action, "")
        if not required:
            return {
                "authorized": False,
                "error": f"Unsupported email action: {action}",
            }
        if required not in state.get("allowed_tools", []):
            return {
                "authorized": False,
                "required_permission": required,
                "error": f"Unauthorized email action: {action}",
            }
        return {"authorized": True, "required_permission": required}

    @staticmethod
    def _after_authorize(state: EmailAgentState) -> str:
        return "execute" if state.get("authorized") else "finish"

    def _execute(self, state: EmailAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress(
            "executing_email_tool",
            action=state.get("action", ""),
        )
        try:
            result = self.email_tool(state.get("request", {}))
        except Exception as exc:
            return {
                "tool_result": {"status": "failed", "answer": str(exc)},
                "error": str(exc),
            }
        return {"tool_result": result}

    @staticmethod
    def _inspect(state: EmailAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress("inspecting_email_result")
        result = state.get("tool_result", {})
        status = result.get("status")
        if status in {"configuration_error", "failed", "unsupported"}:
            return {}
        return {}

    @staticmethod
    def _after_inspect(state: EmailAgentState) -> str:
        result = state.get("tool_result", {})
        if result.get("status") in {"configuration_error", "failed", "unsupported"}:
            return "finish"
        if result.get("status") == "confirmation_required":
            return "validate_send"
        if state.get("action") in {"list_recent", "get_message", "draft_reply"}:
            return "analyze"
        return "finish"

    def _analyze(self, state: EmailAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress("analyzing_email_content")
        result = state.get("tool_result", {})
        if state.get("action") == "list_recent":
            messages = result.get("messages", [])
            return {"analysis": self._analyze_messages(messages)}
        if state.get("action") == "draft_reply":
            draft = result.get("draft")
            if isinstance(draft, dict):
                revised, analysis = self._review_draft(draft)
                updated = dict(result)
                updated["draft"] = revised
                return {"tool_result": updated, "analysis": analysis}
        return {"analysis": {"reviewed": True}}

    def _analyze_messages(self, messages: Any) -> dict[str, Any]:
        if not isinstance(messages, list) or not messages:
            return {"messages": [], "reviewed": True}
        fallback = {
            "messages": [
                {
                    "message_id": item.get("message_id", ""),
                    "priority": self._heuristic_priority(item),
                    "needs_reply": False,
                    "summary": item.get("snippet", ""),
                }
                for item in messages
                if isinstance(item, dict)
            ],
            "reviewed": True,
        }
        if self.llm_client is None:
            return fallback
        try:
            payload = self.llm_client.complete_json(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="system",
                        content=(
                            "分析邮件优先级和是否需要回复。只输出 JSON："
                            "{\"messages\":[{\"message_id\":\"...\","
                            "\"priority\":\"high|medium|low\","
                            "\"needs_reply\":true,\"summary\":\"...\"}]}。"
                        ),
                    ),
                    LLMMessage(role="user", content=f"邮件：{messages}"),
                ]
            )
            analyzed = payload.get("messages")
            if isinstance(analyzed, list):
                return {"messages": analyzed, "reviewed": True}
        except (LLMClientError, ValueError, TypeError):
            pass
        return fallback

    def _review_draft(
        self,
        draft: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        fallback = (draft, {"reviewed": True, "tone": "neutral", "risk_flags": []})
        if self.llm_client is None:
            return fallback
        try:
            payload = self.llm_client.complete_json(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="system",
                        content=(
                            "检查回复草稿的语气、清晰度和风险。只输出 JSON："
                            "{\"body\":\"...\",\"tone\":\"...\","
                            "\"risk_flags\":[...] }。不得添加用户未提供的承诺。"
                        ),
                    ),
                    LLMMessage(role="user", content=f"草稿：{draft}"),
                ]
            )
        except (LLMClientError, ValueError, TypeError):
            return fallback
        body = str(payload.get("body", "")).strip()
        revised = {**draft, "body": body or draft.get("body", "")}
        flags = payload.get("risk_flags", [])
        return revised, {
            "reviewed": True,
            "tone": str(payload.get("tone", "neutral")),
            "risk_flags": flags if isinstance(flags, list) else [],
        }

    @staticmethod
    def _validate_send(state: EmailAgentState) -> dict[str, Any]:
        state["execution_context"].report_progress("validating_send_plan")
        result = state.get("tool_result", {})
        plan = result.get("plan")
        if not isinstance(plan, dict):
            return {"error": "Email confirmation payload is missing a send plan."}
        risk_flags: list[str] = []
        recipient = str(plan.get("to", "")).strip()
        if not recipient or not parseaddr(recipient)[1]:
            risk_flags.append("invalid_recipient")
        if not str(plan.get("body", "")).strip():
            risk_flags.append("empty_body")
        if result.get("action") != "email.send":
            risk_flags.append("invalid_action")
        if not result.get("requires_confirmation"):
            risk_flags.append("confirmation_flag_missing")
        if risk_flags:
            return {
                "risk_flags": risk_flags,
                "error": "Email send plan failed deterministic validation.",
            }
        return {"risk_flags": []}

    @staticmethod
    def _finish(state: EmailAgentState) -> dict[str, Any]:
        return {}

    @staticmethod
    def _heuristic_priority(message: dict[str, Any]) -> str:
        text = f"{message.get('subject', '')} {message.get('snippet', '')}".lower()
        high_markers = ["面试", "offer", "录用", "紧急", "urgent", "deadline", "截止"]
        return "high" if any(marker in text for marker in high_markers) else "medium"


# Compatibility alias for the previous adapter class name.
EmailSubAgent = EmailGraphAgent
