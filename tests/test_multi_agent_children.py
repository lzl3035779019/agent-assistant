from pmaa.multi_agent.agents.adapters import (
    DailyBriefAgent,
    EmailSubAgent,
    InformationMonitorAgent,
    MemorySubAgent,
)
from pmaa.multi_agent.agents.catalog import build_default_agent_registry
from pmaa.multi_agent.agents.web_research import WebResearchAgent
from pmaa.multi_agent.blackboard import InMemoryBlackboard
from pmaa.multi_agent.contracts import (
    AgentMessageType,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from pmaa.multi_agent.runtime import AgentExecutionContext, CentralAgentRuntime
from pmaa.schemas.memory import (
    MemoryCandidate,
    MemoryRecord,
    MemoryValidation,
)
from pmaa.schemas.task import Source


def context_for(task: AgentTask) -> AgentExecutionContext:
    blackboard = InMemoryBlackboard()
    blackboard.add_task(task)
    return AgentExecutionContext(task=task, blackboard=blackboard)


def test_web_research_agent_runs_its_graph_and_returns_evidence() -> None:
    def search(query: str) -> list[Source]:
        return [
            Source(title="Official", url="https://example.com/official", snippet=query),
            Source(title="Docs", url="https://example.org/docs", snippet=query),
        ]

    task = AgentTask(
        assigned_to="web_research",
        objective="Research LangGraph",
        allowed_tools=["web_search"],
    )
    agent = WebResearchAgent(search, max_rounds=2)

    result = agent(task, context_for(task))

    assert result.status == AgentStatus.COMPLETED
    assert len(result.evidence) == 2
    assert result.output["sufficient"] is True


def test_web_research_agent_returns_partial_when_search_fails() -> None:
    agent = WebResearchAgent(lambda query: [], max_rounds=2)
    task = AgentTask(
        assigned_to="web_research",
        objective="Research unavailable topic",
        allowed_tools=["web_search"],
    )

    result = agent(task, context_for(task))

    assert result.status == AgentStatus.PARTIAL
    assert result.output["sources"] == []


class FakeMemory:
    def retrieve(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        return [
            MemoryRecord(
                type="preference",
                content="用户喜欢简洁回答",
                confidence=0.9,
            )
        ]


def test_memory_subagent_retrieves_structured_memories() -> None:
    task = AgentTask(
        assigned_to="memory",
        objective="Get response preferences",
        context={"mode": "retrieve", "query": "回答偏好"},
        allowed_tools=["memory.read"],
    )
    result = MemorySubAgent(FakeMemory())(task, context_for(task))

    assert result.status == AgentStatus.COMPLETED
    assert result.output["memories"][0]["type"] == "preference"
    assert result.output["workflow"] == ["retrieve"]


class FakeConsolidatingMemory(FakeMemory):
    def consolidate(self, **kwargs) -> list[MemoryCandidate]:
        return [
            MemoryCandidate(
                type="preference",
                content="用户喜欢徒步旅行。",
                confidence=0.9,
            ),
            MemoryCandidate(
                type="profile",
                content="今天北京天气很好。",
                confidence=0.9,
            ),
        ]

    def validate(self, candidate: MemoryCandidate) -> MemoryValidation:
        should_save = candidate.type == "preference"
        return MemoryValidation(
            should_save=should_save,
            reason="stable_memory" if should_save else "transient_or_realtime",
        )

    def update(self, candidates: list[MemoryCandidate]) -> list[MemoryRecord]:
        return [MemoryRecord(**candidate.model_dump()) for candidate in candidates]


def test_memory_subagent_runs_extract_validate_update_graph() -> None:
    task = AgentTask(
        assigned_to="memory",
        objective="Consolidate conversation memory",
        context={
            "mode": "consolidate",
            "user_input": "我喜欢徒步旅行",
            "assistant_answer": "记住了",
        },
        allowed_tools=["memory.read", "memory.write"],
    )

    result = MemorySubAgent(FakeConsolidatingMemory())(task, context_for(task))

    assert result.status == AgentStatus.COMPLETED
    assert result.output["workflow"] == ["extract", "validate", "update"]
    assert len(result.output["candidates"]) == 2
    assert len(result.output["saved"]) == 1
    assert result.output["saved"][0]["content"] == "用户喜欢徒步旅行。"


class FakeEmailTool:
    def __call__(self, request):
        return {
            "status": "confirmation_required",
            "action": "email.send",
            "requires_confirmation": True,
            "plan": {"to": "user@example.com", "subject": "Hello", "body": "Hi"},
        }


def test_email_subagent_never_sends_and_returns_confirmation() -> None:
    task = AgentTask(
        assigned_to="email",
        objective="Draft and send email",
        context={
            "email_request": {
                "action": "prepare_send",
                "to": "user@example.com",
                "subject": "Hello",
                "body": "Hi",
            }
        },
        allowed_tools=["email.draft"],
    )

    result = EmailSubAgent(FakeEmailTool())(task, context_for(task))

    assert result.status == AgentStatus.WAITING_CONFIRMATION
    assert result.output["pending_action"]["action"] == "email.send"
    assert result.output["workflow"][-1] == "validate_send_plan"


class FakeInboxTool:
    def __call__(self, request):
        return {
            "status": "completed",
            "answer": "读取到两封邮件。",
            "messages": [
                {
                    "message_id": "1",
                    "subject": "面试安排",
                    "snippet": "请确认明天下午的面试时间",
                },
                {
                    "message_id": "2",
                    "subject": "每周资讯",
                    "snippet": "本周技术资讯",
                },
            ],
        }


def test_email_subagent_analyzes_inbox_priority() -> None:
    task = AgentTask(
        assigned_to="email",
        objective="查看最近邮件",
        context={"email_request": {"action": "list_recent", "limit": 5}},
        allowed_tools=["email.list"],
    )

    result = EmailSubAgent(FakeInboxTool())(task, context_for(task))

    assert result.status == AgentStatus.COMPLETED
    assert result.output["analysis"]["messages"][0]["priority"] == "high"
    assert result.output["workflow"] == [
        "understand",
        "authorize",
        "execute",
        "inspect",
        "analyze",
    ]


class UnsafeEmailTool:
    def __call__(self, request):
        return {
            "status": "confirmation_required",
            "action": "email.send",
            "requires_confirmation": False,
            "plan": {"to": "user@example.com", "subject": "Hello", "body": "Hi"},
        }


def test_email_subagent_rejects_send_plan_without_confirmation_flag() -> None:
    task = AgentTask(
        assigned_to="email",
        objective="发送邮件",
        context={
            "email_request": {
                "action": "prepare_send",
                "to": "user@example.com",
                "subject": "Hello",
                "body": "Hi",
            }
        },
        allowed_tools=["email.draft"],
    )

    result = EmailSubAgent(UnsafeEmailTool())(task, context_for(task))

    assert result.status == AgentStatus.FAILED
    assert "confirmation_flag_missing" in result.output["risk_flags"]


def test_daily_brief_requests_dependencies_through_supervisor() -> None:
    task = AgentTask(assigned_to="daily_brief", objective="生成今日简报")
    context = context_for(task)

    result = DailyBriefAgent()(task, context)
    messages = context.blackboard.list_messages(task.task_id)
    delegation_messages = [
        message
        for message in messages
        if message.message_type == AgentMessageType.DELEGATION_REQUEST
    ]

    assert result.status == AgentStatus.WAITING_DEPENDENCY
    assert len(delegation_messages) == 4
    assert all(message.receiver == "supervisor" for message in delegation_messages)


def test_daily_brief_runs_full_graph_with_complete_dependencies() -> None:
    task = AgentTask(
        assigned_to="daily_brief",
        objective="生成今日简报",
        context={
            "current_date": "2026-07-23",
            "dependency_results": {
                "email": {
                    "messages": [
                        {
                            "message_id": "mail-1",
                            "subject": "面试安排",
                            "from_addr": "hr@example.com",
                            "unread": True,
                        }
                    ]
                },
                "news": {
                    "sources": [
                        {"title": "AI update", "url": "https://example.com/news"}
                    ]
                },
                "memory": {
                    "memories": [
                        {"type": "preference", "content": "用户关注 AI 新闻"}
                    ]
                },
                "calendar": {
                    "status": "ok",
                    "events": [{"title": "项目会议", "start": "10:00"}],
                },
            }
        },
    )

    result = DailyBriefAgent()(task, context_for(task))

    assert result.status == AgentStatus.COMPLETED
    assert result.output["missing_sources"] == []
    assert "生成日期：2026-07-23" in result.output["brief"]
    assert result.output["quality"]["passed"] is True
    assert result.output["workflow"] == [
        "collect_dependencies",
        "normalize_inputs",
        "prioritize_items",
        "compose_brief",
        "quality_check",
        "finalize",
    ]


def test_daily_brief_builds_news_request_from_selected_topics() -> None:
    task = AgentTask(
        assigned_to="daily_brief",
        objective="生成今日简报",
        context={
            "dependency_results": {
                "interest_topics.read": {
                    "status": "ok",
                    "topics": [
                        {
                            "name": "AI 与大模型",
                            "query": "今天 AI 大模型的重要发布",
                        },
                        {
                            "name": "求职与招聘",
                            "query": "今天 AI 工程岗位机会",
                        },
                    ],
                },
                "email": {"messages": []},
                "memory": {"memories": []},
                "calendar": {"status": "ok", "events": []},
            }
        },
    )
    context = context_for(task)

    result = DailyBriefAgent()(task, context)
    messages = context.blackboard.list_messages(task.task_id)
    requests = [
        message
        for message in messages
        if message.message_type == AgentMessageType.DELEGATION_REQUEST
    ]

    assert result.status == AgentStatus.WAITING_DEPENDENCY
    assert len(requests) == 1
    assert requests[0].content["target_capability"] == "web_research"
    assert "AI 与大模型" in requests[0].content["objective"]
    assert "求职与招聘" in requests[0].content["objective"]


def test_daily_brief_discloses_unavailable_calendar() -> None:
    task = AgentTask(
        assigned_to="daily_brief",
        objective="生成今日简报",
        context={
            "dependency_results": {
                "email": {"messages": []},
                "news": {"sources": []},
                "memory": {"memories": []},
                "calendar.read": {
                    "status": "unavailable",
                    "events": [],
                    "reason": "not configured",
                },
            }
        },
    )

    result = DailyBriefAgent()(task, context_for(task))

    assert result.status == AgentStatus.PARTIAL
    assert result.output["missing_sources"] == ["calendar"]
    assert "数据缺失" in result.output["brief"]


def test_monitor_requests_research_through_supervisor() -> None:
    task = AgentTask(
        assigned_to="information_monitor",
        objective="检查 Vercel 的最新招聘变化",
    )
    context = context_for(task)

    result = InformationMonitorAgent()(task, context)
    messages = context.blackboard.list_messages(task.task_id)
    delegation_messages = [
        message
        for message in messages
        if message.message_type == AgentMessageType.DELEGATION_REQUEST
    ]

    assert result.status == AgentStatus.WAITING_DEPENDENCY
    assert delegation_messages[0].content["target_capability"] == "web_research"


def test_default_catalog_contains_exactly_five_child_agents() -> None:
    registry = build_default_agent_registry(
        search_tool=lambda query: [],
        memory_agent=FakeMemory(),
        email_tool=FakeEmailTool(),
    )

    assert {spec.agent_id for spec in registry.list_specs()} == {
        "web_research",
        "memory",
        "email",
        "daily_brief",
        "information_monitor",
    }
    assert hasattr(registry.get_handler("memory"), "graph")
    assert hasattr(registry.get_handler("email"), "graph")
    assert hasattr(registry.get_handler("daily_brief"), "graph")
    assert hasattr(registry.get_handler("information_monitor"), "graph")


def test_runtime_can_resume_a_suspended_agent_task() -> None:
    attempts = 0

    def handler(task: AgentTask, context: AgentExecutionContext) -> AgentResult:
        nonlocal attempts
        attempts += 1
        status = (
            AgentStatus.WAITING_DEPENDENCY
            if attempts == 1
            else AgentStatus.COMPLETED
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=task.assigned_to,
            status=status,
        )

    from pmaa.multi_agent.contracts import AgentSpec
    from pmaa.multi_agent.registry import AgentRegistry

    registry = AgentRegistry()
    registry.register(
        AgentSpec(agent_id="brief", name="Brief", description="Brief"), handler
    )
    runtime = CentralAgentRuntime(registry)
    task = AgentTask(task_id="brief-1", assigned_to="brief", objective="Brief")

    first = runtime.dispatch(task)
    second = runtime.dispatch(task)

    assert first.status == AgentStatus.WAITING_DEPENDENCY
    assert second.status == AgentStatus.COMPLETED
    assert runtime.blackboard.get_result(task.task_id) == second
