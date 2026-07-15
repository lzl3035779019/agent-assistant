from pmaa.agents.policy import PolicyAgent
from pmaa.workflow.graph import run_workflow


class StubPolicyLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete_text(self, messages):
        return ""

    def complete_json(self, messages):
        self.calls += 1
        return self.payload


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


def test_policy_keeps_obvious_follow_up_as_deterministic_rule():
    llm = StubPolicyLLM(
        {
            "intent": "search_query",
            "task_kind": "search_task",
            "execution_mode": "tool_call",
            "need_memory": False,
            "need_tools": True,
            "required_tool": "search",
            "should_plan": False,
            "requires_confirmation": False,
            "risk_level": "low",
            "confidence": 0.9,
            "reason": "should not be used",
        }
    )
    policy = PolicyAgent(llm_client=llm)

    decision = policy.decide("继续", conversation_context="上一轮在分析 LangGraph。")

    assert decision.intent == "follow_up"
    assert llm.calls == 0


def test_policy_uses_llm_for_non_obvious_context_dependency():
    llm = StubPolicyLLM(
        {
            "intent": "project_optimization",
            "task_kind": "research_task",
            "execution_mode": "plan_and_execute",
            "need_memory": False,
            "need_tools": True,
            "required_tool": "search",
            "should_plan": True,
            "requires_confirmation": False,
            "risk_level": "low",
            "confidence": 0.87,
            "reason": "当前问题是完整任务，不依赖上一轮上下文。",
        }
    )
    policy = PolicyAgent(llm_client=llm)

    decision = policy.decide("这个项目怎么优化", conversation_context="上一轮在讨论天气。")

    assert llm.calls == 1
    assert decision.intent == "project_optimization"
    assert decision.intent != "follow_up"


def test_policy_forces_realtime_news_queries_to_search_over_browser_skill():
    llm = StubPolicyLLM(
        {
            "intent": "news_query",
            "task_kind": "realtime_query",
            "execution_mode": "tool_call",
            "need_memory": False,
            "need_tools": True,
            "required_tool": "skill:agent_browser",
            "should_plan": False,
            "requires_confirmation": True,
            "risk_level": "medium",
            "confidence": 0.95,
            "reason": "LLM selected browser skill for news extraction.",
        }
    )
    policy = PolicyAgent(llm_client=llm)

    decision = policy.decide("我喜欢了解新闻，帮我推送今天最火的ai有关的新闻")

    assert decision.task_kind == "realtime_query"
    assert decision.required_tool == "search"
    assert decision.execution_mode == "tool_call"
    assert decision.requires_confirmation is False
    assert decision.risk_level == "low"


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
