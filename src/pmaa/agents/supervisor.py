import re
from typing import Literal

from pydantic import BaseModel, Field

from pmaa.config import settings
from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.schemas.task import FinalResult


ExecutionMode = Literal[
    "direct_answer",
    "tool_call",
    "plan_and_execute",
    "clarification",
]


class IntentDecision(BaseModel):
    intent: str
    task_kind: str = "unknown"
    execution_mode: ExecutionMode = "clarification"
    need_tools: bool = False
    required_tool: str = "none"
    should_plan: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class SupervisorAgent:
    name = "supervisor"
    supported_tools = {"search", "knowledge", "wiki_get_page"}

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        knowledge_available: bool | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._knowledge_available = (
            settings.gbrain_mcp_enabled
            if knowledge_available is None
            else knowledge_available
        )

    def should_plan(self, user_input: str) -> bool:
        return self.classify_intent(user_input).should_plan

    def classify_intent(
        self,
        user_input: str,
        conversation_context: str = "",
    ) -> IntentDecision:
        normalized = user_input.strip().lower()
        rule_decision = self._classify_by_rules(normalized, conversation_context)
        if rule_decision is not None:
            if self._llm_client is None or self._is_deterministic_rule(rule_decision):
                return self._normalize_decision(rule_decision)

        if self._llm_client is not None:
            llm_decision = self._classify_by_llm(user_input, conversation_context)
            if llm_decision is not None:
                normalized_decision = self._normalize_decision(llm_decision)
                if normalized_decision.confidence < 0.55:
                    return self._normalize_decision(
                        IntentDecision(
                            intent="ambiguous",
                            task_kind=normalized_decision.task_kind,
                            execution_mode="clarification",
                            need_tools=False,
                            required_tool="none",
                            should_plan=False,
                            confidence=normalized_decision.confidence,
                            reason="LLM 路由置信度过低，需要用户补充任务目标。",
                        )
                    )
                return normalized_decision

        return IntentDecision(
            intent="ambiguous",
            task_kind="unknown",
            execution_mode="clarification",
            need_tools=False,
            required_tool="none",
            should_plan=False,
            confidence=0.45,
            reason="输入目标不明确，无法安全选择执行方式。",
        )

    def direct_answer(
        self,
        user_input: str,
        conversation_context: str = "",
        intent: str = "",
        task_kind: str = "",
    ) -> str:
        normalized = user_input.strip().lower()
        if self._is_model_identity_question(normalized):
            return (
                "我是 PMAA 个人多 Agent 助手。"
                f"当前配置的 LLM 模型是 `{settings.llm_model}`，"
                f"提供方是 `{settings.llm_provider}`。"
            )
        if intent == "casual_chat" or task_kind == "casual_chat":
            return "你好，我是 PMAA 个人多 Agent 助手，可以帮你规划、检索、写作和整理复杂任务。"
        if self._llm_client is not None:
            try:
                return self._llm_client.complete_text(
                    [
                        LLMMessage(
                            role="system",
                            content=(
                                "你是 PMAA 的直接回答模块。"
                                "当用户请求不需要外部实时信息、不需要复杂规划时，"
                                "直接完成用户请求。回答使用中文，简洁自然。"
                                "不要提及内部路由、Agent、工具或工作流。"
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
            except LLMClientError:
                pass
        return "我理解你的请求，但当前没有可用的 LLM 来生成这类直接回答。请检查模型配置后再试。"

    def clarification_answer(self) -> str:
        return (
            "请补充一下你想完成的具体目标，例如：需要我搜索资料、写一份报告、"
            "制定计划，还是分析某段内容？"
        )

    def finalize(self, result: FinalResult) -> FinalResult:
        return result

    def _classify_by_rules(
        self,
        normalized_input: str,
        conversation_context: str,
    ) -> IntentDecision | None:
        if self._is_model_identity_question(normalized_input):
            return IntentDecision(
                intent="model_identity",
                task_kind="self_status",
                execution_mode="direct_answer",
                need_tools=False,
                required_tool="none",
                should_plan=False,
                confidence=0.99,
                reason="用户询问系统自身模型信息。",
            )
        if self._is_wiki_page_request(normalized_input):
            return IntentDecision(
                intent="wiki_get_page",
                task_kind="knowledge_task",
                execution_mode="tool_call",
                need_tools=True,
                required_tool="wiki_get_page",
                should_plan=False,
                confidence=0.99,
                reason="用户明确指定了 GBrain Wiki 页面，直接读取页面详情。",
            )
        if self._is_knowledge_request(normalized_input):
            return IntentDecision(
                intent="knowledge_query",
                task_kind="knowledge_task",
                execution_mode="tool_call",
                need_tools=True,
                required_tool="knowledge",
                should_plan=False,
                confidence=0.99,
                reason="用户明确要求基于本地知识库回答，优先检索 GBrain Wiki。",
            )
        if self._knowledge_available and self._is_implicit_knowledge_question(normalized_input):
            return IntentDecision(
                intent="knowledge_query",
                task_kind="knowledge_task",
                execution_mode="tool_call",
                need_tools=True,
                required_tool="knowledge",
                should_plan=False,
                confidence=0.96,
                reason="检测到领域知识问答，GBrain 知识库可用，先检索本地证据而非直接凭模型常识回答。",
            )
        if normalized_input in {"hi", "hello", "你好", "嗨"}:
            return IntentDecision(
                intent="casual_chat",
                task_kind="casual_chat",
                execution_mode="direct_answer",
                need_tools=False,
                required_tool="none",
                should_plan=False,
                confidence=0.98,
                reason="用户只是简单问候。",
            )
        if self._is_casual_direct_request(normalized_input):
            return IntentDecision(
                intent="casual_response",
                task_kind="direct_response",
                execution_mode="direct_answer",
                need_tools=False,
                required_tool="none",
                should_plan=False,
                confidence=0.98,
                reason="用户提出了明确的轻量直接回答请求，不需要检索、规划或澄清。",
            )
        if self._is_simple_direct_request(normalized_input):
            return IntentDecision(
                intent="simple_direct_request",
                task_kind="direct_response",
                execution_mode="direct_answer",
                need_tools=False,
                required_tool="none",
                should_plan=False,
                confidence=0.86,
                reason="用户请求明确，且不需要工具或复杂规划。",
            )
        if self._is_memory_write_request(normalized_input):
            return IntentDecision(
                intent="memory_update",
                task_kind="memory_task",
                execution_mode="direct_answer",
                need_tools=False,
                required_tool="none",
                should_plan=False,
                confidence=0.94,
                reason="用户明确要求写入长期记忆，不需要搜索或规划。",
            )
        if self._has_user_conversation_context(conversation_context):
            return IntentDecision(
                intent="follow_up",
                task_kind="contextual_task",
                execution_mode="plan_and_execute",
                need_tools=True,
                required_tool="search",
                should_plan=True,
                confidence=0.82,
                reason="存在历史上下文，短追问也应进入任务工作流。",
            )
        if self._has_workflow_keyword(normalized_input):
            task_kind = self._guess_task_kind(normalized_input)
            execution_mode: ExecutionMode = (
                "tool_call" if task_kind == "search_task" else "plan_and_execute"
            )
            return IntentDecision(
                intent=task_kind,
                task_kind=task_kind,
                execution_mode=execution_mode,
                need_tools=True,
                required_tool="search",
                should_plan=execution_mode == "plan_and_execute",
                confidence=0.86,
                reason="命中非实时任务型关键词。",
            )
        return None

    def _normalize_decision(self, decision: IntentDecision) -> IntentDecision:
        updates: dict[str, object] = {}
        reason_suffixes: list[str] = []

        required_tool = (decision.required_tool or "none").strip().lower()
        if required_tool in {"", "null", "none"}:
            required_tool = "none"
        if required_tool != "none" and not self._is_supported_tool(required_tool):
            required_tool = "search"
            reason_suffixes.append("当前仅注册 search 工具，已将工具归一为 search。")
        updates["required_tool"] = required_tool

        tool_required = decision.need_tools or required_tool != "none"
        if decision.task_kind in {"search_task", "realtime_query"}:
            tool_required = True

        if decision.execution_mode == "clarification":
            updates.update(
                {
                    "need_tools": False,
                    "required_tool": "none",
                    "should_plan": False,
                }
            )
        elif decision.should_plan or decision.execution_mode == "plan_and_execute":
            updates.update(
                {
                    "execution_mode": "plan_and_execute",
                    "need_tools": True,
                    "required_tool": required_tool if required_tool != "none" else "search",
                    "should_plan": True,
                }
            )
        elif tool_required:
            updates.update(
                {
                    "execution_mode": "tool_call",
                    "need_tools": True,
                    "required_tool": required_tool if required_tool != "none" else "search",
                    "should_plan": False,
                }
            )
        else:
            updates.update(
                {
                    "execution_mode": "direct_answer",
                    "need_tools": False,
                    "required_tool": "none",
                    "should_plan": False,
                }
            )

        if reason_suffixes:
            updates["reason"] = " ".join([decision.reason, *reason_suffixes]).strip()
        return decision.model_copy(update=updates)

    @staticmethod
    def _is_deterministic_rule(decision: IntentDecision) -> bool:
        return decision.intent in {
            "model_identity",
            "knowledge_query",
            "wiki_get_page",
            "casual_chat",
            "casual_response",
            "memory_update",
            "follow_up",
        }

    @classmethod
    def _is_supported_tool(cls, tool_name: str) -> bool:
        return tool_name in cls.supported_tools or tool_name.startswith("skill:")

    @staticmethod
    def _has_user_conversation_context(conversation_context: str) -> bool:
        cleaned = conversation_context.strip()
        if not cleaned:
            return False
        for marker in ["<!-- Skill Catalog -->", "<!-- Selected Skill -->", "<!-- Skills Snapshot -->", "长期记忆："]:
            if marker in cleaned:
                cleaned = cleaned.split(marker, 1)[0].strip()
        return bool(cleaned)

    def _classify_by_llm(
        self,
        user_input: str,
        conversation_context: str,
    ) -> IntentDecision | None:
        try:
            payload = self._llm_client.complete_json(
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "你是 PMAA 的企业级意图路由器，只输出 JSON。"
                            "字段必须包含 intent, task_kind, execution_mode, "
                            "need_tools, required_tool, should_plan, confidence, reason。"
                            "execution_mode 只能是 direct_answer, tool_call, "
                            "plan_and_execute, clarification。"
                            "intent 表示用户想做什么，例如 casual_chat, model_identity, "
                            "weather_query, search_query, research_report。"
                            "task_kind 表示任务类型，例如 casual_chat, realtime_query, "
                            "search_task, research_task, writing_task, coding_task。"
                            "如果只需要调用一个工具，execution_mode=tool_call 且 should_plan=false。"
                            "如果需要复杂拆解、多步执行，execution_mode=plan_and_execute 且 should_plan=true。"
                            "当前已注册工具为 search、knowledge、wiki_get_page；没有 weather 工具。"
                            "天气、新闻、股票、物流、实时状态等需要外部新信息的问题应 need_tools=true。"
                        ),
                    ),
                    LLMMessage(
                        role="system",
                        content=(
                            "如果历史上下文包含 <!-- Skill Catalog -->，请只根据每个 skill 的 "
                            "id、name、description 判断是否适合当前任务；不要依赖 triggers。"
                            "如果某个 skill 适合，required_tool 必须写成 skill:<id>。"
                            "只有没有合适 skill 且任务需要外部信息时，才使用 search。"
                        ),
                    ),
                    LLMMessage(
                        role="system",
                        content=(
                            "Registered tools: search = public web or realtime lookup; "
                            "knowledge = local GBrain knowledge base retrieval. "
                            "Use required_tool=knowledge when the user asks about local, private, "
                            "personal, document, note, wiki, or GBrain knowledge. "
                            "Use required_tool=search for public web freshness."
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
            return IntentDecision.model_validate(payload)
        except (LLMClientError, ValueError):
            return None

    @staticmethod
    def _is_model_identity_question(normalized_input: str) -> bool:
        model_identity_keywords = [
            "你是啥模型",
            "你是什么模型",
            "你用的什么模型",
            "你用的是哪个模型",
            "what model are you",
            "which model",
        ]
        return any(keyword in normalized_input for keyword in model_identity_keywords)

    @staticmethod
    def _is_wiki_page_request(normalized_input: str) -> bool:
        return "gbrain://page/" in normalized_input or bool(
            re.search(r"(?:^|[\s，。])wiki/[a-z0-9_./-]+", normalized_input)
        )

    @staticmethod
    def _is_knowledge_request(normalized_input: str) -> bool:
        knowledge_keywords = [
            "知识库",
            "gbrain",
            "wiki",
            "本地知识",
            "个人知识",
            "我的资料",
            "我的文档",
            "上传的文档",
            "已上传文档",
            "local knowledge",
            "knowledge base",
            "personal notes",
        ]
        return any(keyword in normalized_input for keyword in knowledge_keywords)

    @staticmethod
    def _is_implicit_knowledge_question(normalized_input: str) -> bool:
        """Route domain fact questions to GBrain without a magic prefix."""
        domain_terms = [
            "agent",
            "workflow",
            "rag",
            "llm",
            "mcp",
            "embedding",
            "智能体",
            "工作流",
            "检索",
            "向量",
            "知识图谱",
            "大模型",
            "提示词",
            "模型",
        ]
        knowledge_question_markers = [
            "区别",
            "不同",
            "是什么",
            "有哪些",
            "怎么做",
            "为什么",
            "原理",
            "优点",
            "缺点",
            "不足",
            "场景",
            "流程",
            "架构",
            "对比",
            "比较",
        ]
        return any(term in normalized_input for term in domain_terms) and any(
            marker in normalized_input for marker in knowledge_question_markers
        )

    @staticmethod
    def _is_casual_direct_request(normalized_input: str) -> bool:
        """Recognize unambiguous lightweight requests before the LLM router."""
        direct_patterns = [
            r"(?:讲|说|来|给我).{0,8}笑话",
            r"笑话.{0,8}(?:吧|啊|呀)?$",
            r"(?:翻译|改写|润色).{1,120}$",
            r"(?:写|来).{0,8}(?:诗|故事|脑筋急转弯)$",
        ]
        return any(re.search(pattern, normalized_input) for pattern in direct_patterns)

    @staticmethod
    def _is_simple_direct_request(normalized_input: str) -> bool:
        if len(normalized_input) > 80:
            return False
        tool_or_complex_keywords = [
            "今天",
            "现在",
            "最新",
            "实时",
            "天气",
            "新闻",
            "股价",
            "搜索",
            "查询",
            "查找",
            "研究",
            "报告",
            "方案",
            "计划",
            "规划",
            "代码",
            "实现",
            "debug",
            "latest",
            "current",
            "today",
            "weather",
            "news",
            "search",
            "find",
            "research",
            "report",
            "plan",
            "code",
        ]
        if any(keyword in normalized_input for keyword in tool_or_complex_keywords):
            return False
        direct_request_keywords = [
            "讲",
            "说",
            "解释",
            "翻译",
            "改写",
            "润色",
            "取名",
            "起名",
            "想一个",
            "给我一个",
            "列几个",
            "tell me",
            "explain",
            "translate",
            "rewrite",
            "polish",
            "name",
        ]
        return any(keyword in normalized_input for keyword in direct_request_keywords)

    @staticmethod
    def _is_memory_write_request(normalized_input: str) -> bool:
        memory_keywords = [
            "记忆",
            "记住",
            "记下来",
            "保存到记忆",
            "写到记忆",
            "写入记忆",
            "长期记忆",
            "remember",
            "save to memory",
        ]
        stable_fact_keywords = [
            "我叫",
            "我的名字",
            "我是",
            "我希望",
            "我喜欢",
            "我偏好",
            "以后",
            "不要",
            "必须",
        ]
        return any(keyword in normalized_input for keyword in memory_keywords) and any(
            keyword in normalized_input for keyword in stable_fact_keywords
        )

    @staticmethod
    def _has_workflow_keyword(normalized_input: str) -> bool:
        workflow_keywords = [
            "搜索",
            "查询",
            "查找",
            "研究",
            "分析",
            "对比",
            "总结",
            "写",
            "生成",
            "制定",
            "规划",
            "代码",
            "实现",
            "debug",
            "search",
            "find",
            "research",
            "analyze",
            "compare",
            "write",
            "plan",
            "code",
            "implement",
        ]
        return any(keyword in normalized_input for keyword in workflow_keywords)

    @staticmethod
    def _guess_task_kind(normalized_input: str) -> str:
        if any(keyword in normalized_input for keyword in ["代码", "实现", "debug", "code", "implement"]):
            return "coding_task"
        if any(keyword in normalized_input for keyword in ["写", "生成", "报告", "write"]):
            return "writing_task"
        if any(keyword in normalized_input for keyword in ["计划", "规划", "制定", "plan"]):
            return "planning_task"
        if any(keyword in normalized_input for keyword in ["研究", "分析", "对比", "research", "analyze", "compare"]):
            return "research_task"
        if any(keyword in normalized_input for keyword in ["搜索", "查询", "查找", "最新", "search", "find", "latest"]):
            return "search_task"
        return "research_task"
