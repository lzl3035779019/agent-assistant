from pmaa.agents.knowledge import KnowledgeAgent
from pmaa.schemas.task import ExecutionPlan, PlanStep


def test_knowledge_agent_builds_knowledge_tool_request_from_plan_goal():
    agent = KnowledgeAgent()
    plan = ExecutionPlan(
        goal="检索我的 LLM Wiki 里关于 GBrain 的内容",
        steps=[
            PlanStep(
                step_id="knowledge-1",
                description="Search local wiki.",
                agent="knowledge",
                expected_output="Relevant wiki pages.",
            )
        ],
    )

    request = agent.build_tool_request(plan)

    assert request == {
        "tool_name": "knowledge",
        "query": "检索我的 LLM Wiki 里关于 GBrain 的内容",
    }
