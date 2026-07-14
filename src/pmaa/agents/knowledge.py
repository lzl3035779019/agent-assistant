from pmaa.schemas.task import ExecutionPlan


class KnowledgeAgent:
    name = "knowledge"

    def build_tool_request(
        self,
        plan: ExecutionPlan,
        tool_name: str = "knowledge",
        query: str | None = None,
    ) -> dict[str, str]:
        return {
            "tool_name": tool_name,
            "query": query or plan.goal,
        }
