from pmaa.schemas.task import ExecutionPlan


class SearchAgent:
    name = "search"

    def build_tool_request(self, plan: ExecutionPlan) -> dict[str, str]:
        return {
            "tool_name": "search",
            "query": plan.goal,
        }
