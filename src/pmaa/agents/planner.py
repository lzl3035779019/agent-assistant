from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.schemas.task import ExecutionPlan, PlanStep


class PlannerAgent:
    name = "planner"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    def plan(self, user_input: str, conversation_context: str = "") -> ExecutionPlan:
        if self._llm_client is not None:
            user_content = user_input
            if conversation_context.strip():
                user_content = (
                    f"历史对话上下文：\n{conversation_context.strip()}\n\n"
                    f"当前用户任务：\n{user_input}"
                )
            try:
                payload = self._llm_client.complete_json(
                    [
                        LLMMessage(
                            role="system",
                            content=(
                                "你是 PMAA 的 Planner Agent。"
                                "请把用户任务拆成可执行步骤，只输出 JSON 对象。"
                                "JSON 字段必须包含 goal, steps, required_agents, "
                                "expected_output, risk_points。steps 中每项必须包含 "
                                "step_id, description, agent, expected_output。"
                                "v1 只允许使用 search, writer, reflection 三类 agent。"
                            ),
                        ),
                        LLMMessage(role="user", content=user_content),
                    ]
                )
                return ExecutionPlan.model_validate(payload)
            except (LLMClientError, ValueError):
                pass

        return ExecutionPlan(
            goal=user_input,
            steps=[
                PlanStep(
                    step_id="search-1",
                    description=f"Search background information for: {user_input}",
                    agent="search",
                    expected_output="Relevant sources with titles, URLs, and snippets.",
                ),
                PlanStep(
                    step_id="write-1",
                    description="Create a structured answer from the gathered sources.",
                    agent="writer",
                    expected_output="Markdown answer with clear sections.",
                ),
            ],
            required_agents=["search", "writer", "reflection"],
            expected_output="A structured, source-aware answer.",
            risk_points=["Search results may be incomplete or outdated."],
        )
