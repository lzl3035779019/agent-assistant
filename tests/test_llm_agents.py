from pmaa.agents.planner import PlannerAgent
from pmaa.agents.reflection import ReflectionAgent
from pmaa.agents.writer import WriterAgent
from pmaa.llm.client import FakeLLMClient
from pmaa.schemas.task import ExecutionPlan, PlanStep, Source


def test_planner_uses_llm_json_when_client_is_provided():
    client = FakeLLMClient(
        json_payload={
            "goal": "研究 LangGraph",
            "steps": [
                {
                    "step_id": "search-1",
                    "description": "搜索 LangGraph 核心概念",
                    "agent": "search",
                    "expected_output": "资料来源",
                },
                {
                    "step_id": "write-1",
                    "description": "生成学习路线",
                    "agent": "writer",
                    "expected_output": "Markdown 报告",
                },
            ],
            "required_agents": ["search", "writer", "reflection"],
            "expected_output": "学习路线",
            "risk_points": ["资料可能过时"],
        }
    )

    plan = PlannerAgent(llm_client=client).plan("帮我研究 LangGraph")

    assert plan.goal == "研究 LangGraph"
    assert plan.steps[0].description == "搜索 LangGraph 核心概念"


def test_writer_uses_llm_text_when_client_is_provided():
    plan = ExecutionPlan(
        goal="研究 LangGraph",
        steps=[
            PlanStep(
                step_id="search-1",
                description="搜索资料",
                agent="search",
                expected_output="资料",
            )
        ],
    )
    sources = [
        Source(
            title="LangGraph Guide",
            url="https://langchain-ai.github.io/langgraph/",
            snippet="state graph",
        )
    ]
    client = FakeLLMClient(text_payload="# LangGraph 报告\n\n这是 LLM 生成的内容。")

    answer = WriterAgent(llm_client=client).write(plan, sources)

    assert "LLM 生成" in answer


def test_reflection_uses_llm_json_when_client_is_provided():
    client = FakeLLMClient(
        json_payload={
            "passed": True,
            "issues": [],
            "suggested_fix": "",
            "need_retry": False,
        }
    )

    reflection = ReflectionAgent(llm_client=client).reflect(
        "研究 LangGraph",
        "# LangGraph 报告\n\n基于资料来源 [S1]。",
        [
            Source(
                title="source",
                url="https://langchain-ai.github.io/langgraph/",
                snippet="snippet",
            )
        ],
    )

    assert reflection.passed is True
    assert reflection.need_retry is False
