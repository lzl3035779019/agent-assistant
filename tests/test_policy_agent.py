from pmaa.agents.policy import PolicyAgent
from pmaa.workflow.graph import run_workflow


def test_policy_marks_memory_participation_without_deciding_memory_write():
    policy = PolicyAgent()

    decision = policy.decide("我叫小林，写到记忆里去")

    assert decision.intent == "personal_fact_statement"
    assert decision.task_kind == "conversation"
    assert decision.execution_mode == "direct_answer"
    assert decision.need_memory is True
    assert decision.need_tools is False
    assert decision.required_tool == "none"
    assert decision.should_plan is False


def test_policy_exposes_risk_and_confirmation_fields():
    policy = PolicyAgent()

    decision = policy.decide("你好，你是啥模型")

    assert decision.requires_confirmation is False
    assert decision.risk_level == "low"


def test_policy_uses_history_only_for_context_dependent_follow_up():
    policy = PolicyAgent()
    context = "用户刚才在问 LangGraph 和 Agent 的区别。"

    independent = policy.decide(
        "我喜欢跑步打游戏，喜欢旅游，你可以给我推荐几个避暑的旅游胜地吗",
        conversation_context=context,
    )
    follow_up = policy.decide("那它有什么缺点", conversation_context=context)

    assert independent.intent != "follow_up"
    assert "历史上下文" not in independent.reason
    assert follow_up.intent == "follow_up"
    assert follow_up.reason == "当前输入依赖历史上下文，进入上下文任务工作流。"


def test_supervisor_event_includes_policy_fields_for_memory_route(tmp_path):
    from pmaa.agents.memory import MemoryAgent
    from pmaa.storage.memory_store import SQLiteMemoryStore

    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    memory_agent = MemoryAgent(store)

    result = run_workflow(
        "我叫小林，写到记忆里去",
        memory_agent=memory_agent,
        enable_memory=True,
    )

    supervisor_event = next(event for event in result.events if event.agent == "supervisor")
    assert supervisor_event.output["intent"] == "personal_fact_statement"
    assert supervisor_event.output["need_memory"] is True
    assert supervisor_event.output["requires_confirmation"] is False
    assert supervisor_event.output["risk_level"] == "low"
