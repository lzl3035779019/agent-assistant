import pytest
from pydantic import ValidationError

from pmaa.multi_agent.agents.information_monitor import InformationMonitorAgent
from pmaa.multi_agent.blackboard import InMemoryBlackboard
from pmaa.multi_agent.contracts import AgentStatus, AgentTask
from pmaa.multi_agent.runtime import AgentExecutionContext
from pmaa.schemas.monitor import MonitorRule
from pmaa.storage.monitor_store import SQLiteMonitorStore


def execution_context(task: AgentTask) -> AgentExecutionContext:
    blackboard = InMemoryBlackboard()
    blackboard.add_task(task)
    return AgentExecutionContext(task=task, blackboard=blackboard)


def test_monitor_schema_rejects_paper_target() -> None:
    with pytest.raises(ValidationError):
        MonitorRule(
            name="Paper updates",
            target_type="paper",
            target="Agent papers",
            query="latest agent papers",
        )


def test_monitor_store_persists_rules_and_snapshots(tmp_path) -> None:
    store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    rule = store.save_rule(
        MonitorRule(
            name="Vercel jobs",
            target_type="jobs",
            target="Vercel",
            query="Vercel engineering jobs",
        )
    )
    snapshot = store.save_snapshot(
        rule.rule_id,
        [{"title": "Backend Engineer", "url": "https://vercel.com/jobs/1"}],
    )

    assert store.get_rule(rule.rule_id) is not None
    assert store.list_rules(enabled_only=True)[0].target_type == "jobs"
    assert store.latest_snapshot(rule.rule_id) == snapshot
    assert store.delete_rule(rule.rule_id) is True
    assert store.latest_snapshot(rule.rule_id) is None


def test_monitor_agent_creates_baseline_then_reports_only_new_items(tmp_path) -> None:
    store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    rule = MonitorRule(
        name="Vercel jobs",
        target_type="jobs",
        target="Vercel",
        query="Vercel engineering jobs",
    )
    agent = InformationMonitorAgent(store=store)
    first_task = AgentTask(
        assigned_to="information_monitor",
        objective="检查 Vercel 招聘变化",
        context={
            "rules": [rule.model_dump()],
            "observations": [
                {"title": "Backend Engineer", "url": "https://vercel.com/jobs/1"}
            ],
        },
        allowed_tools=["monitor.store"],
    )

    first = agent(first_task, execution_context(first_task))

    assert first.status == AgentStatus.COMPLETED
    assert first.output["baseline_created"] == 1
    assert first.output["important_changes"] == []

    second_task = AgentTask(
        assigned_to="information_monitor",
        objective="再次检查 Vercel 招聘变化",
        context={
            "rules": [rule.model_dump()],
            "observations": [
                {"title": "Backend Engineer", "url": "https://vercel.com/jobs/1"},
                {"title": "AI Engineer", "url": "https://vercel.com/jobs/2"},
            ],
        },
        allowed_tools=["monitor.store"],
    )

    second = agent(second_task, execution_context(second_task))

    assert second.status == AgentStatus.COMPLETED
    assert second.output["baseline_created"] == 0
    assert len(second.output["important_changes"]) == 1
    assert second.output["important_changes"][0]["change"]["title"] == "AI Engineer"


def test_monitor_agent_rule_management_uses_repository(tmp_path) -> None:
    store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    agent = InformationMonitorAgent(store=store)
    task = AgentTask(
        assigned_to="information_monitor",
        objective="添加 Vercel GitHub 更新监控",
        context={
            "action": "create_rule",
            "rule": {
                "name": "Vercel GitHub",
                "target_type": "github",
                "target": "vercel/vercel",
                "query": "vercel/vercel GitHub releases",
            },
        },
        allowed_tools=["monitor.store"],
    )

    result = agent(task, execution_context(task))

    assert result.status == AgentStatus.COMPLETED
    assert result.output["rule"]["target_type"] == "github"
    assert len(store.list_rules()) == 1


def test_monitor_agent_detects_content_update_on_same_url(tmp_path) -> None:
    store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    rule = store.save_rule(
        MonitorRule(
            name="Vercel jobs",
            target_type="jobs",
            target="Vercel",
            query="Vercel engineering jobs",
        )
    )
    store.save_snapshot(
        rule.rule_id,
        [
            {
                "title": "Backend Engineer",
                "url": "https://vercel.com/jobs/1",
                "snippet": "Remote role",
            }
        ],
    )
    agent = InformationMonitorAgent(store=store)
    task = AgentTask(
        assigned_to="information_monitor",
        objective="检查 Vercel 招聘变化",
        context={
            "rules": [rule.model_dump()],
            "observations": [
                {
                    "title": "Backend Engineer",
                    "url": "https://vercel.com/jobs/1",
                    "snippet": "Role closed",
                }
            ],
        },
        allowed_tools=["monitor.store"],
    )

    result = agent(task, execution_context(task))

    assert result.status == AgentStatus.COMPLETED
    assert len(result.output["important_changes"]) == 1
    assert result.output["comparisons"][0]["updated_items"][0]["snippet"] == "Role closed"


def test_monitor_agent_requests_github_tool_and_consumes_artifact(tmp_path) -> None:
    store = SQLiteMonitorStore(tmp_path / "monitor.sqlite3")
    rule = MonitorRule(
        name="Popular AI projects",
        target_type="github",
        target="热门 AI 项目",
        query="LLM Agent RAG MCP 热门项目",
    )
    task = AgentTask(
        assigned_to="information_monitor",
        objective="检查热门 AI 项目",
        context={"rules": [rule.model_dump()]},
        allowed_tools=["monitor.store", "github.read"],
    )
    context = execution_context(task)
    agent = InformationMonitorAgent(store=store)

    waiting = agent(task, context)

    assert waiting.status == AgentStatus.WAITING_DEPENDENCY
    messages = context.blackboard.list_messages(task.task_id)
    assert messages[-1].content["target_capability"] == "github.read"

    context.blackboard.put_artifact(
        task.task_id,
        "github.read",
        {
            "status": "completed",
            "rule_id": rule.rule_id,
            "items": [
                {
                    "title": "example/agent-kit",
                    "url": "https://github.com/example/agent-kit",
                    "stars": 12000,
                    "latest_release": "v1.0.0",
                }
            ],
        },
    )
    completed = agent(task, context)

    assert completed.status == AgentStatus.COMPLETED
    assert completed.output["baseline_created"] == 1
    assert store.latest_snapshot(rule.rule_id) is not None


def test_github_change_threshold_ignores_noise_but_keeps_releases() -> None:
    previous = {
        "url": "https://github.com/example/agent-kit",
        "stars": 1000,
        "latest_release": "v1.0.0",
        "snippet": "Agent framework",
    }

    assert InformationMonitorAgent._meaningfully_changed(
        previous,
        {**previous, "stars": 1010, "pushed_at": "2026-07-23T00:00:00Z"},
        target_type="github",
    ) is False
    assert InformationMonitorAgent._meaningfully_changed(
        previous,
        {**previous, "stars": 1020},
        target_type="github",
    ) is True
    assert InformationMonitorAgent._meaningfully_changed(
        previous,
        {**previous, "latest_release": "v1.1.0"},
        target_type="github",
    ) is True
