from pmaa.agents.policy import PolicyAgent, PolicyDecision
from pmaa.config import settings
from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.schemas.task import FinalResult


IntentDecision = PolicyDecision


class SupervisorAgent:
    name = "supervisor"
    supported_tools = PolicyAgent.supported_tools

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
        self._policy_agent = PolicyAgent(
            llm_client=llm_client,
            knowledge_available=self._knowledge_available,
        )

    def should_plan(self, user_input: str) -> bool:
        return self.classify_intent(user_input).should_plan

    def classify_intent(
        self,
        user_input: str,
        conversation_context: str = "",
    ) -> IntentDecision:
        return self._policy_agent.decide(user_input, conversation_context)

    def direct_answer(
        self,
        user_input: str,
        conversation_context: str = "",
        intent: str = "",
        task_kind: str = "",
    ) -> str:
        normalized = user_input.strip().lower()
        if PolicyAgent._is_model_identity_question(normalized):
            return (
                "我是 PMAA 个人多 Agent 助手。"
                f"当前配置的 LLM 模型是 `{settings.llm_model}`，"
                f"提供方是 `{settings.llm_provider}`。"
            )
        if intent == "casual_chat" or task_kind == "casual_chat":
            return "你好，我是 PMAA 个人多 Agent 助手，可以帮你规划、检索、写作和整理复杂任务。"
        if intent == "personal_fact_statement":
            return "好的，我会让记忆系统处理这条信息。"
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
