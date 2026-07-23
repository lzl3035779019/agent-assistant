from __future__ import annotations

from pmaa.agents.memory import MemoryAgent as LegacyMemoryAgent
from pmaa.llm.client import LLMClient
from pmaa.multi_agent.agents.adapters import (
    MemorySubAgent,
)
from pmaa.multi_agent.agents.daily_brief import DailyBriefAgent
from pmaa.multi_agent.agents.email import EmailSubAgent
from pmaa.multi_agent.agents.information_monitor import InformationMonitorAgent
from pmaa.multi_agent.agents.web_research import WebResearchAgent
from pmaa.multi_agent.contracts import AgentSpec
from pmaa.multi_agent.registry import AgentRegistry
from pmaa.tools.email_tool import EmailTool
from pmaa.tools.factory import SearchTool
from pmaa.storage.monitor_store import SQLiteMonitorStore


def build_default_agent_registry(
    *,
    search_tool: SearchTool,
    llm_client: LLMClient | None = None,
    memory_agent: LegacyMemoryAgent | None = None,
    email_tool: EmailTool | None = None,
    monitor_store: SQLiteMonitorStore | None = None,
) -> AgentRegistry:
    registry = AgentRegistry()
    entries = [
        (
            AgentSpec(
                agent_id="web_research",
                name="Web Research Agent",
                description="从公开互联网获取实时、可信、可引用的信息并检查证据。",
                capabilities=["web_research", "public_realtime_lookup"],
                allowed_tools=["web_search"],
                max_retries=2,
            ),
            WebResearchAgent(search_tool, llm_client),
        ),
        (
            AgentSpec(
                agent_id="memory",
                name="Memory Agent",
                description="检索、提取、验证和维护用户长期记忆。",
                capabilities=["memory.retrieve", "memory.consolidate"],
                allowed_tools=["memory.read", "memory.write"],
                max_retries=1,
            ),
            MemorySubAgent(memory_agent or LegacyMemoryAgent(llm_client=llm_client)),
        ),
        (
            AgentSpec(
                agent_id="email",
                name="Email Agent",
                description="读取、分类、摘要和起草邮件，发送前必须等待确认。",
                capabilities=["email.today_unread", "email.read", "email.draft"],
                allowed_tools=["email.list", "email.read", "email.draft"],
                max_retries=1,
            ),
            EmailSubAgent(email_tool or EmailTool(), llm_client),
        ),
        (
            AgentSpec(
                agent_id="daily_brief",
                name="Daily Brief Agent",
                description="汇总当天邮件、热点、日程和用户偏好，生成个人简报。",
                capabilities=["brief.generate"],
                allowed_tools=["interest_topics.read"],
                max_retries=1,
            ),
            DailyBriefAgent(llm_client),
        ),
        (
            AgentSpec(
                agent_id="information_monitor",
                name="Information Monitor Agent",
                description="监控公司、招聘、GitHub 项目和技术博客的重要变化。",
                capabilities=["monitor.manage", "monitor.analyze"],
                allowed_tools=["monitor.store", "rss.read", "github.read"],
                max_retries=2,
            ),
            InformationMonitorAgent(llm_client, monitor_store),
        ),
    ]
    for spec, handler in entries:
        registry.register(spec, handler)
    return registry
