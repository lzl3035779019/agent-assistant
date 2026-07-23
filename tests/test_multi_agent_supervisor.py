import pytest

from pmaa.llm.client import FakeLLMClient
from pmaa.multi_agent.contracts import AgentResult, AgentSpec, AgentStatus, AgentTask
from pmaa.multi_agent.registry import AgentRegistry
from pmaa.multi_agent.supervisor import (
    HierarchicalSupervisor,
    SupervisorDecision,
    SupervisorPlanError,
)


def handler(task: AgentTask, context: object) -> AgentResult:
    return AgentResult(
        task_id=task.task_id,
        agent_id=task.assigned_to,
        status=AgentStatus.COMPLETED,
    )


def make_registry() -> AgentRegistry:
    registry = AgentRegistry()
    specs = [
        AgentSpec(
            agent_id="web_research",
            name="Web Research Agent",
            description="Researches public web information.",
            capabilities=["research"],
            allowed_tools=["web_search"],
            max_retries=2,
        ),
        AgentSpec(
            agent_id="memory",
            name="Memory Agent",
            description="Retrieves and maintains long-term memory.",
            capabilities=["memory.retrieve", "memory.consolidate"],
            allowed_tools=["memory.read", "memory.write"],
            max_retries=1,
        ),
        AgentSpec(
            agent_id="email",
            name="Email Agent",
            description="Reads, classifies and drafts email.",
            capabilities=["email.read", "email.draft"],
            allowed_tools=["email.list", "email.read", "email.draft"],
            max_retries=1,
        ),
        AgentSpec(
            agent_id="daily_brief",
            name="Daily Brief Agent",
            description="Builds a daily personal brief.",
            capabilities=["brief.generate"],
            max_retries=1,
        ),
        AgentSpec(
            agent_id="information_monitor",
            name="Information Monitor Agent",
            description="Tracks configured public information sources.",
            capabilities=["monitor.run"],
            allowed_tools=["monitor.store", "rss.read", "github.read"],
            max_retries=2,
        ),
    ]
    for spec in specs:
        registry.register(spec, handler)
    return registry


def test_model_identity_is_deterministic_direct_answer() -> None:
    supervisor = HierarchicalSupervisor(make_registry(), knowledge_available=True)

    decision = supervisor.analyze("你是什么模型？")

    assert decision.mode == "direct_answer"
    assert decision.intent == "model_identity"


def test_llm_can_plan_independent_child_agents() -> None:
    llm = FakeLLMClient(
        json_payload={
            "intent": "personalized_research",
            "mode": "delegate",
            "tasks": [
                {
                    "task_id": "memory-1",
                    "assigned_to": "memory",
                    "objective": "Retrieve travel preferences",
                    "allowed_tools": ["memory.read"],
                    "max_retries": 1,
                },
                {
                    "task_id": "web-1",
                    "assigned_to": "web_research",
                    "objective": "Research summer destinations",
                    "allowed_tools": ["web_search"],
                    "max_retries": 2,
                },
            ],
            "direct_tool": "none",
            "requires_confirmation": False,
            "confidence": 0.94,
            "reason": "Needs preferences and current web evidence.",
        }
    )
    supervisor = HierarchicalSupervisor(
        make_registry(), llm, knowledge_available=True
    )

    decision = supervisor.analyze("根据我的喜好推荐近期避暑地")

    assert decision.mode == "delegate"
    assert {task.assigned_to for task in decision.tasks} == {
        "memory",
        "web_research",
    }


def test_supervisor_normalizes_common_llm_schema_variants() -> None:
    llm = FakeLLMClient(
        json_payload={
            "intent": "weather_query",
            "mode": "delegate",
            "tasks": [
                {
                    "assigned_to": "web_research",
                    "objective": "查询南昌青山湖今日天气",
                    "context": "需要实时天气信息",
                    "constraints": "使用可靠来源",
                    "allowed_tools": "web_search",
                    "priority": "normal",
                }
            ],
            "direct_tool": None,
            "tool_arguments": None,
            "confidence": 0.92,
            "reason": "需要实时数据。",
        }
    )

    decision = HierarchicalSupervisor(
        make_registry(), llm, knowledge_available=True
    ).analyze("南昌青山湖今天天气怎么样")

    assert decision.reason == "需要实时数据。"
    assert decision.tasks[0].priority == 5
    assert decision.tasks[0].context == {"request_context": "需要实时天气信息"}
    assert decision.tasks[0].constraints == ["使用可靠来源"]


def test_supervisor_reports_schema_fallback_instead_of_llm_unavailable() -> None:
    llm = FakeLLMClient(
        json_payload={
            "intent": "bad_plan",
            "mode": "delegate",
            "tasks": [{"assigned_to": "ghost", "objective": "invalid"}],
            "confidence": 0.8,
        }
    )

    decision = HierarchicalSupervisor(
        make_registry(), llm, knowledge_available=True
    ).analyze("查一下今天的天气")

    assert "结构校验" in decision.reason
    assert "LLM 不可用" not in decision.reason


def test_fallback_routes_daily_brief_before_email() -> None:
    llm = FakeLLMClient(
        json_payload={
            "intent": "bad_plan",
            "mode": "delegate",
            "tasks": [{"assigned_to": "ghost", "objective": "invalid"}],
            "confidence": 0.8,
        }
    )

    decision = HierarchicalSupervisor(
        make_registry(), llm, knowledge_available=True
    ).analyze("根据今日未读邮件和新闻生成今日个人简报")

    assert decision.tasks[0].assigned_to == "daily_brief"
    assert decision.intent == "daily_brief"


def test_local_knowledge_remains_a_supervisor_tool() -> None:
    supervisor = HierarchicalSupervisor(make_registry(), knowledge_available=True)

    decision = supervisor.analyze("从我的知识库查一下 Agentic RAG")

    assert decision.mode == "tool"
    assert decision.direct_tool == "knowledge"
    assert decision.tasks == []


def test_unknown_agent_is_rejected() -> None:
    supervisor = HierarchicalSupervisor(make_registry(), knowledge_available=True)
    decision = SupervisorDecision(
        mode="delegate",
        tasks=[AgentTask(assigned_to="ghost", objective="Do work")],
    )

    with pytest.raises(KeyError, match="Unknown agent"):
        supervisor.validate_decision(decision)


def test_cycle_in_task_dependencies_is_rejected() -> None:
    supervisor = HierarchicalSupervisor(make_registry(), knowledge_available=True)
    decision = SupervisorDecision(
        mode="delegate",
        tasks=[
            AgentTask(
                task_id="one",
                assigned_to="memory",
                objective="One",
                allowed_tools=["memory.read"],
                depends_on=["two"],
            ),
            AgentTask(
                task_id="two",
                assigned_to="memory",
                objective="Two",
                allowed_tools=["memory.read"],
                depends_on=["one"],
            ),
        ],
    )

    with pytest.raises(SupervisorPlanError, match="dependency cycle"):
        supervisor.validate_decision(decision)


def test_email_send_intent_forces_confirmation() -> None:
    supervisor = HierarchicalSupervisor(make_registry(), knowledge_available=True)
    decision = SupervisorDecision(
        intent="email_send",
        mode="delegate",
        tasks=[
            AgentTask(
                assigned_to="email",
                objective="Draft an email for confirmation",
                allowed_tools=["email.draft"],
            )
        ],
        requires_confirmation=False,
    )

    validated = supervisor.validate_decision(decision)

    assert validated.requires_confirmation is True


def test_supervisor_normalizes_numeric_task_ids_and_dependencies() -> None:
    payload = {
        "intent": "research",
        "mode": "delegate",
        "tasks": [
            {
                "task_id": 1,
                "assigned_to": "web_research",
                "objective": "collect evidence",
                "depends_on": [],
            },
            {
                "task_id": 2,
                "parent_task_id": 1,
                "assigned_to": "memory",
                "objective": "store durable preferences",
                "depends_on": [1],
            },
        ],
        "direct_tool": "none",
        "tool_arguments": {},
    }

    normalized = HierarchicalSupervisor._normalize_llm_payload(payload)
    decision = SupervisorDecision.model_validate(normalized)

    assert decision.tasks[0].task_id == "1"
    assert decision.tasks[1].task_id == "2"
    assert decision.tasks[1].parent_task_id == "1"
    assert decision.tasks[1].depends_on == ["1"]
