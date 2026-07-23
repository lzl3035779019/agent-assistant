from pmaa.llm.client import FakeLLMClient
from pmaa.multi_agent.agents.adapters import DailyBriefAgent
from pmaa.multi_agent.agents.information_monitor import InformationMonitorAgent
from pmaa.multi_agent.agents.web_research import WebResearchAgent
from pmaa.multi_agent.blackboard import InMemoryBlackboard
from pmaa.multi_agent.contracts import AgentResult, AgentSpec, AgentStatus, AgentTask
from pmaa.multi_agent.orchestrator import MultiAgentOrchestrator
from pmaa.multi_agent.registry import AgentRegistry
from pmaa.multi_agent.runtime import AgentExecutionContext, CentralAgentRuntime
from pmaa.multi_agent.supervisor import HierarchicalSupervisor
from pmaa.schemas.task import Source
from pmaa.schemas.monitor import MonitorRule
from pmaa.storage.monitor_store import SQLiteMonitorStore
from pmaa.tools.registry import ToolRegistry


def memory_handler(
    task: AgentTask,
    context: AgentExecutionContext,
) -> AgentResult:
    mode = task.context.get("mode", "retrieve")
    output = (
        {"memories": [{"type": "preference", "content": "用户关注 AI"}]}
        if mode == "retrieve"
        else {"candidates": [], "saved": []}
    )
    return AgentResult(
        task_id=task.task_id,
        agent_id="memory",
        status=AgentStatus.COMPLETED,
        summary="Memory handled",
        output=output,
        confidence=0.9,
    )


def web_sources(query: str) -> list[Source]:
    return [
        Source(
            title="Official update",
            url="https://example.org/official",
            snippet=f"Official evidence for {query}",
        ),
        Source(
            title="Independent report",
            url="https://example.net/report",
            snippet=f"Independent evidence for {query}",
        ),
    ]


def base_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(
        AgentSpec(
            agent_id="web_research",
            name="Web Research",
            description="Researches the public web.",
            capabilities=["web_research"],
            allowed_tools=["web_search"],
            max_retries=2,
        ),
        WebResearchAgent(web_sources),
    )
    registry.register(
        AgentSpec(
            agent_id="memory",
            name="Memory",
            description="Maintains long-term memory.",
            capabilities=["memory.retrieve", "memory.consolidate"],
            allowed_tools=["memory.read", "memory.write"],
            max_retries=1,
        ),
        memory_handler,
    )
    return registry


def make_orchestrator(
    registry: AgentRegistry,
    supervisor: HierarchicalSupervisor | None = None,
    *,
    knowledge_tool=None,
    supervisor_tools=None,
) -> MultiAgentOrchestrator:
    blackboard = InMemoryBlackboard()
    runtime = CentralAgentRuntime(registry, blackboard=blackboard, max_concurrency=4)
    active_supervisor = supervisor or HierarchicalSupervisor(
        registry,
        knowledge_available=knowledge_tool is not None,
    )
    return MultiAgentOrchestrator(
        registry=registry,
        supervisor=active_supervisor,
        runtime=runtime,
        knowledge_tool=knowledge_tool,
        supervisor_tools=supervisor_tools,
    )


def test_orchestrator_runs_research_and_consolidates_memory() -> None:
    orchestrator = make_orchestrator(base_registry())

    result = orchestrator.run("搜索 LangGraph 最新信息")

    assert result.tool_result["architecture"] == "hierarchical_multi_agent"
    assert len(result.sources) == 2
    assert "资料来源" in result.final_result.answer
    agents = [event.agent for event in result.events]
    assert "supervisor" in agents
    assert "web_research" in agents
    assert "memory" in agents


def test_orchestrator_explicit_assignment_bypasses_intent_routing() -> None:
    registry = base_registry()

    def brief_handler(task: AgentTask, context: AgentExecutionContext) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id="daily_brief",
            status=AgentStatus.COMPLETED,
            output={"brief": "# 今日简报\n\n已按系统任务生成。"},
            confidence=0.9,
        )

    registry.register(
        AgentSpec(
            agent_id="daily_brief",
            name="Daily Brief Agent",
            description="Builds a daily brief.",
            capabilities=["brief.generate"],
        ),
        brief_handler,
    )
    invalid_llm = FakeLLMClient(
        json_payload={
            "intent": "email_task",
            "mode": "delegate",
            "tasks": [{"assigned_to": "email", "objective": "wrong route"}],
            "confidence": 0.9,
        }
    )
    orchestrator = make_orchestrator(
        registry,
        HierarchicalSupervisor(registry, invalid_llm, knowledge_available=False),
    )

    result = orchestrator.run(
        "根据未读邮件和新闻生成今日简报",
        assigned_agent="daily_brief",
    )

    decision = result.tool_result["supervisor_decision"]
    assert decision["intent"] == "system_daily_brief"
    assert decision["tasks"][0]["assigned_to"] == "daily_brief"
    assert "已按系统任务生成" in result.final_result.answer


def test_orchestrator_dispatches_independent_tasks_as_one_batch() -> None:
    registry = base_registry()
    llm = FakeLLMClient(
        json_payload={
            "intent": "parallel_research",
            "mode": "delegate",
            "tasks": [
                {
                    "task_id": "web-a",
                    "assigned_to": "web_research",
                    "objective": "Research aspect A",
                    "allowed_tools": ["web_search"],
                    "max_retries": 2,
                },
                {
                    "task_id": "web-b",
                    "assigned_to": "web_research",
                    "objective": "Research aspect B",
                    "allowed_tools": ["web_search"],
                    "max_retries": 2,
                },
            ],
            "direct_tool": "none",
            "confidence": 0.95,
            "reason": "Independent research aspects.",
        }
    )
    supervisor = HierarchicalSupervisor(
        registry,
        llm,
        knowledge_available=False,
    )
    orchestrator = make_orchestrator(registry, supervisor)

    result = orchestrator.run("Compare two research aspects")
    lifecycle = [
        (event.agent, event.event_type)
        for event in result.events
        if event.agent == "web_research"
    ]

    first_completion = next(
        index for index, item in enumerate(lifecycle) if item[1] == "task_completed"
    )
    assert [item[1] for item in lifecycle[:first_completion]] == [
        "task_started",
        "task_started",
    ]


def test_daily_brief_delegates_dependencies_and_resumes() -> None:
    registry = base_registry()

    def email_handler(task: AgentTask, context: AgentExecutionContext) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id="email",
            status=AgentStatus.COMPLETED,
            summary="Unread mail collected",
            output={"messages": [{"subject": "Interview"}]},
            confidence=0.9,
        )

    registry.register(
        AgentSpec(
            agent_id="email",
            name="Email",
            description="Reads email.",
            capabilities=["email.today_unread"],
            allowed_tools=["email.list"],
        ),
        email_handler,
    )
    registry.register(
        AgentSpec(
            agent_id="daily_brief",
            name="Daily Brief",
            description="Builds a daily brief.",
            capabilities=["brief.generate"],
        ),
        DailyBriefAgent(),
    )
    llm = FakeLLMClient(
        json_payload={
            "intent": "daily_brief",
            "mode": "delegate",
            "tasks": [
                {
                    "task_id": "brief-1",
                    "assigned_to": "daily_brief",
                    "objective": "生成今日简报",
                    "allowed_tools": [],
                    "max_retries": 1,
                }
            ],
            "direct_tool": "none",
            "confidence": 0.96,
            "reason": "Daily brief requested.",
        }
    )
    supervisor = HierarchicalSupervisor(registry, llm, knowledge_available=False)
    orchestrator = make_orchestrator(registry, supervisor)

    result = orchestrator.run("生成今日简报")
    brief_result = result.tool_result["agent_results"]["brief-1"]

    assert brief_result["status"] == "partial"
    assert "brief" in brief_result["output"]
    assert any(
        event.agent == "daily_brief" and event.event_type == "task_resumed"
        for event in result.events
    )
    assert any(
        event.event_type == "delegation_unresolved"
        and event.output["capability"] == "calendar.read"
        for event in result.events
    )


def test_daily_brief_receives_calendar_result_from_supervisor_tool() -> None:
    registry = base_registry()

    def email_handler(task: AgentTask, context: AgentExecutionContext) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id="email",
            status=AgentStatus.COMPLETED,
            output={"messages": [{"subject": "Interview"}]},
        )

    registry.register(
        AgentSpec(
            agent_id="email",
            name="Email",
            description="Reads email.",
            capabilities=["email.today_unread"],
            allowed_tools=["email.list"],
        ),
        email_handler,
    )
    registry.register(
        AgentSpec(
            agent_id="daily_brief",
            name="Daily Brief",
            description="Builds a daily brief.",
            capabilities=["brief.generate"],
        ),
        DailyBriefAgent(),
    )
    llm = FakeLLMClient(
        json_payload={
            "intent": "daily_brief",
            "mode": "delegate",
            "tasks": [
                {
                    "task_id": "brief-calendar",
                    "assigned_to": "daily_brief",
                    "objective": "生成今日简报",
                    "allowed_tools": [],
                }
            ],
            "direct_tool": "none",
            "confidence": 0.96,
            "reason": "Daily brief requested.",
        }
    )
    tools = ToolRegistry()
    tools.register(
        "calendar.read",
        lambda request: {
            "status": "ok",
            "events": [{"title": "面试", "start": "10:00"}],
        },
    )
    orchestrator = make_orchestrator(
        registry,
        HierarchicalSupervisor(registry, llm, knowledge_available=False),
        supervisor_tools=tools,
    )

    result = orchestrator.run("生成今日简报")
    brief_result = result.tool_result["agent_results"]["brief-calendar"]

    assert brief_result["status"] == "completed"
    assert brief_result["output"]["missing_sources"] == []
    assert any(
        event.event_type == "supervisor_tool_completed"
        and event.output["tool"] == "calendar.read"
        for event in result.events
    )


def test_knowledge_query_uses_supervisor_tool_not_child_agent() -> None:
    registry = base_registry()
    orchestrator = make_orchestrator(registry, knowledge_tool=web_sources)

    result = orchestrator.run("从我的知识库查询 Agentic RAG")

    decision = result.tool_result["supervisor_decision"]
    assert decision["mode"] == "tool"
    assert decision["direct_tool"] == "knowledge"
    assert decision["tasks"] == []
    assert len(result.sources) == 2


def test_monitor_delegates_multiple_rules_in_parallel_and_builds_baselines(
    tmp_path,
) -> None:
    registry = base_registry()
    store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    rules = [
        MonitorRule(
            name="Vercel jobs",
            target_type="jobs",
            target="Vercel",
            query="Vercel engineering jobs",
        ),
        MonitorRule(
            name="LangGraph GitHub",
            target_type="github",
            target="langchain-ai/langgraph",
            query="langchain-ai/langgraph GitHub releases",
        ),
    ]
    registry.register(
        AgentSpec(
            agent_id="information_monitor",
            name="Information Monitor",
            description="Monitors configured targets.",
            capabilities=["monitor.analyze"],
            allowed_tools=["monitor.store"],
        ),
        InformationMonitorAgent(store=store),
    )
    llm = FakeLLMClient(
        json_payload={
            "intent": "monitor_updates",
            "mode": "delegate",
            "tasks": [
                {
                    "task_id": "monitor-1",
                    "assigned_to": "information_monitor",
                    "objective": "检查我的监控目标更新",
                    "context": {"rules": [rule.model_dump() for rule in rules]},
                    "allowed_tools": ["monitor.store"],
                }
            ],
            "direct_tool": "none",
            "confidence": 0.95,
            "reason": "Monitor task requested.",
        }
    )
    supervisor = HierarchicalSupervisor(registry, llm, knowledge_available=False)
    orchestrator = make_orchestrator(registry, supervisor)

    result = orchestrator.run("检查我的监控目标更新")
    monitor_result = result.tool_result["agent_results"]["monitor-1"]
    research_lifecycle = [
        event.event_type
        for event in result.events
        if event.agent == "web_research"
    ]

    assert monitor_result["status"] == "completed"
    assert monitor_result["output"]["baseline_created"] == 2
    first_completion = research_lifecycle.index("task_completed")
    assert research_lifecycle[:first_completion] == ["task_started", "task_started"]
    assert "首次基线" in result.final_result.answer


def test_monitor_routes_multiple_github_rules_through_supervisor_tools(tmp_path) -> None:
    registry = base_registry()
    store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    rules = [
        MonitorRule(
            name="LangGraph",
            target_type="github",
            target="langchain-ai/langgraph",
            query="LangGraph releases",
        ),
        MonitorRule(
            name="MCP servers",
            target_type="github",
            target="modelcontextprotocol/servers",
            query="MCP server releases",
        ),
    ]
    registry.register(
        AgentSpec(
            agent_id="information_monitor",
            name="Information Monitor",
            description="Monitors configured targets.",
            capabilities=["monitor.analyze"],
            allowed_tools=["monitor.store", "github.read"],
        ),
        InformationMonitorAgent(store=store),
    )
    llm = FakeLLMClient(
        json_payload={
            "intent": "monitor_updates",
            "mode": "delegate",
            "tasks": [
                {
                    "task_id": "github-monitor",
                    "assigned_to": "information_monitor",
                    "objective": "检查 GitHub 监控目标",
                    "context": {"rules": [rule.model_dump() for rule in rules]},
                    "allowed_tools": ["monitor.store", "github.read"],
                }
            ],
            "direct_tool": "none",
            "confidence": 0.95,
            "reason": "GitHub monitor task requested.",
        }
    )
    tools = ToolRegistry()

    def github_tool(request: dict) -> dict:
        target = request["monitor_target"]
        return {
            "status": "completed",
            "rule_id": request["monitor_rule_id"],
            "items": [
                {
                    "title": target,
                    "url": f"https://github.com/{target}",
                    "stars": 1000,
                    "latest_release": "v1.0.0",
                }
            ],
        }

    tools.register("github.read", github_tool)
    orchestrator = make_orchestrator(
        registry,
        HierarchicalSupervisor(registry, llm, knowledge_available=False),
        supervisor_tools=tools,
    )

    result = orchestrator.run("检查 GitHub 监控目标")
    monitor_result = result.tool_result["agent_results"]["github-monitor"]

    assert monitor_result["status"] == "completed"
    assert monitor_result["output"]["baseline_created"] == 2
    assert sum(
        event.event_type == "supervisor_tool_completed"
        and event.output["tool"] == "github.read"
        for event in result.events
    ) == 2
