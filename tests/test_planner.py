from pmaa.agents.planner import PlannerAgent


def test_planner_generates_structured_execution_plan():
    planner = PlannerAgent()

    plan = planner.plan("帮我研究 LangGraph 的核心概念，并生成学习路线")

    assert plan.goal
    assert len(plan.steps) >= 2
    assert plan.steps[0].agent == "search"
    assert plan.steps[-1].agent == "writer"
