from uuid import uuid4
import re
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph

from pmaa.agents.knowledge import KnowledgeAgent
from pmaa.agents.memory import MemoryAgent
from pmaa.agents.planner import PlannerAgent
from pmaa.agents.reflection import ReflectionAgent
from pmaa.agents.search import SearchAgent
from pmaa.agents.supervisor import SupervisorAgent
from pmaa.agents.tool import ToolAgent
from pmaa.agents.writer import WriterAgent
from pmaa.llm.client import LLMClient, create_llm_client
from pmaa.schemas.task import AgentEvent, ExecutionPlan, FinalResult, PlanStep, ReflectionResult
from pmaa.skills.registry import LocalSkillRegistry
from pmaa.skills.actions import create_default_action_registry
from pmaa.skills.tool_binding import SkillToolBindingService
from pmaa.tools.factory import create_knowledge_tool, create_search_tool, create_wiki_get_page_tool
from pmaa.tools.registry import ToolRegistry
from pmaa.tools.search_tool import mock_search
from pmaa.workflow.state import WorkflowGraphState, WorkflowResult


def _event(task_id: str, agent: str, event_type: str, output: dict) -> AgentEvent:
    return AgentEvent(task_id=task_id, agent=agent, event_type=event_type, output=output)


def _append_event(
    state: WorkflowGraphState,
    agent: str,
    event_type: str,
    output: dict,
) -> list[AgentEvent]:
    return [
        *state.get("events", []),
        _event(state["task_id"], agent, event_type, output),
    ]


def _skill_id_from_tool_name(tool_name: str) -> str:
    if not tool_name.startswith("skill:"):
        return ""
    return tool_name.removeprefix("skill:").strip()


def _pending_confirmation_from_tool_result(tool_result: object) -> dict:
    if not isinstance(tool_result, dict):
        return {}
    if tool_result.get("status") != "confirmation_required":
        return {}
    return {
        "status": "confirmation_required",
        "tool_name": tool_result.get("tool_name", ""),
        "skill_id": tool_result.get("skill_id", ""),
        "action": tool_result.get("action", ""),
        "permission_level": tool_result.get("permission_level", ""),
        "requires_confirmation": bool(tool_result.get("requires_confirmation", True)),
        "plan": tool_result.get("plan", {}),
        "rollback": tool_result.get("rollback", {}),
    }


def _sources_and_retrieval_diagnostic(tool_result: object) -> tuple[list, dict]:
    if isinstance(tool_result, list):
        return tool_result, {}
    if isinstance(tool_result, dict):
        sources = tool_result.get("sources")
        diagnostic = tool_result.get("retrieval_diagnostic")
        return (sources if isinstance(sources, list) else []), (
            diagnostic if isinstance(diagnostic, dict) else {}
        )
    return [], {}


def _tool_input_for_direct_call(
    tool_name: str,
    user_input: str,
    registry: ToolRegistry | None = None,
) -> object:
    if not tool_name.startswith("skill:"):
        return user_input
    if not _is_browser_skill_tool(tool_name):
        return user_input
    url = _extract_url_to_open(user_input)
    if (
        not url
        and registry is not None
        and registry.has("search")
        and _should_resolve_site_with_search(user_input)
    ):
        url = _resolve_official_site_url(user_input, registry)
    return _build_browser_task_request(user_input, url)


def _is_browser_skill_tool(tool_name: str) -> bool:
    normalized = tool_name.removeprefix("skill:").lower()
    return "browser" in normalized


def _build_browser_task_request(user_input: str, start_url: str = "") -> dict[str, object]:
    args: dict[str, object] = {
        "goal": user_input.strip(),
        "steps": _infer_browser_steps(user_input, start_url),
    }
    if start_url:
        args["start_url"] = start_url
    return {
        "action": "browser.task",
        "args": args,
    }


def _infer_browser_steps(user_input: str, start_url: str = "") -> list[str]:
    text = user_input.lower()
    steps: list[str] = []
    if start_url:
        steps.append("打开网页")
    if any(marker in text for marker in ("截图", "截屏", "screenshot", "capture")):
        steps.append("截图")
    if any(marker in text for marker in ("点击", "click")):
        steps.append("点击页面元素")
    if any(marker in text for marker in ("填写", "填表", "表单", "fill", "form")):
        steps.append("填写表单")
    if any(marker in text for marker in ("抽取", "提取", "抓取", "读取", "read", "extract", "scrape")):
        steps.append("抽取页面内容")
    if any(marker in text for marker in ("检查", "测试", "inspect", "test", "qa")):
        steps.append("检查页面")
    if not steps:
        steps.append("执行浏览器任务")
    return steps


def _resolve_official_site_url(user_input: str, registry: ToolRegistry) -> str:
    query = _official_site_search_query(user_input)
    if not query:
        return ""
    try:
        results = registry.call("search", query)
    except Exception:
        return ""
    if not isinstance(results, list):
        return ""
    return _homepage_url(_select_official_site_url(results))


def _should_resolve_site_with_search(user_input: str) -> bool:
    text = user_input.lower()
    has_open_intent = any(
        marker in text
        for marker in (
            "打开",
            "访问",
            "进入",
            "open",
            "visit",
        )
    )
    has_site_target = any(
        marker in text
        for marker in (
            "官网",
            "官方网站",
            "网站",
            "official",
            "website",
            "site",
        )
    )
    return has_open_intent and has_site_target


def _official_site_search_query(user_input: str) -> str:
    query = user_input.strip()
    query = re.sub(
        r"^(打开|访问|进入|打开一下|帮我打开|open|visit)\s*",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()
    query = re.sub(r"(的)?(网页|网站|页面)\s*$", "", query).strip()
    if not query:
        return ""
    lowered = query.lower()
    if "官网" not in query and "official" not in lowered:
        query = f"{query} 官网"
    return query


def _select_official_site_url(results: list[object]) -> str:
    candidates = [_source_url(result) for result in results]
    candidates = [url for url in candidates if url]
    if not candidates:
        return ""

    best_url = candidates[0]
    best_score = -1
    for result in results:
        url = _source_url(result)
        if not url:
            continue
        text = _source_text(result)
        score = 0
        if any(marker in text for marker in ("official site", "official website", "官网", "官方网站")):
            score += 10
        if any(marker in text for marker in ("docs", "documentation", "文档", "百科", "wikipedia")):
            score -= 3
        if _looks_like_homepage(url):
            score += 2
        if score > best_score:
            best_score = score
            best_url = url
    return best_url


def _source_url(source: object) -> str:
    if isinstance(source, dict):
        return str(source.get("url", "") or "")
    return str(getattr(source, "url", "") or "")


def _source_text(source: object) -> str:
    if isinstance(source, dict):
        parts = [source.get("title", ""), source.get("snippet", ""), source.get("url", "")]
    else:
        parts = [
            getattr(source, "title", ""),
            getattr(source, "snippet", ""),
            getattr(source, "url", ""),
        ]
    return " ".join(str(part) for part in parts if part).lower()


def _looks_like_homepage(url: str) -> bool:
    match = re.match(r"https?://[^/]+/?$", url, flags=re.IGNORECASE)
    return bool(match)


def _homepage_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}"


def _extract_url_to_open(user_input: str) -> str:
    match = re.search(r"https?://[^\s，。！？]+", user_input, flags=re.IGNORECASE)
    if match:
        return match.group(0)
    normalized = user_input.lower()
    product_official_sites = [
        (("文心一言", "文小言", "ernie bot", "yiyan"), "https://yiyan.baidu.com"),
        (("文心大模型", "wenxin"), "https://wenxin.baidu.com"),
    ]
    for keywords, url in product_official_sites:
        if any(keyword in normalized for keyword in keywords):
            return url
    if "百度" in normalized or "baidu" in normalized:
        return "https://www.baidu.com"
    domain_match = re.search(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", normalized)
    if domain_match:
        return f"https://{domain_match.group(0)}"
    return ""


def _extract_wiki_slug_from_input(user_input: str) -> str:
    text = user_input.strip()
    marker = "gbrain://page/"
    if marker in text:
        return text.split(marker, 1)[1].split()[0].strip()
    for token in text.replace("，", " ").replace("。", " ").split():
        if token.startswith("wiki/"):
            return token.strip()
    return text


def build_workflow_graph(
    llm_client: LLMClient | None = None,
    use_configured_llm: bool = False,
    use_configured_search: bool = False,
    memory_agent: MemoryAgent | None = None,
    enable_memory: bool = False,
    skill_registry: LocalSkillRegistry | None = None,
    enable_skills: bool = False,
    skill_tool_binding_service: SkillToolBindingService | None = None,
):
    registry = ToolRegistry()
    search_tool = create_search_tool() if use_configured_search else mock_search
    registry.register("search", search_tool)
    knowledge_tool = create_knowledge_tool()
    if knowledge_tool is not None:
        registry.register("knowledge", knowledge_tool)
    wiki_get_page_tool = create_wiki_get_page_tool()
    if wiki_get_page_tool is not None:
        registry.register("wiki_get_page", wiki_get_page_tool)

    active_llm_client = llm_client
    if active_llm_client is None and use_configured_llm:
        active_llm_client = create_llm_client()

    supervisor = SupervisorAgent(
        llm_client=active_llm_client,
        knowledge_available=knowledge_tool is not None,
    )
    planner = PlannerAgent(llm_client=active_llm_client)
    searcher = SearchAgent()
    knowledge_agent = KnowledgeAgent()
    tool_agent = ToolAgent(registry)
    writer = WriterAgent(llm_client=active_llm_client)
    reflector = ReflectionAgent(llm_client=active_llm_client)
    active_memory_agent = memory_agent if enable_memory else None
    if active_memory_agent is None and enable_memory:
        active_memory_agent = MemoryAgent(llm_client=active_llm_client)
    active_skill_registry = skill_registry if enable_skills else None
    if active_skill_registry is None and enable_skills:
        active_skill_registry = LocalSkillRegistry()
    if active_skill_registry is not None:
        binding_service = skill_tool_binding_service or SkillToolBindingService(
            action_registry=create_default_action_registry(),
        )
        binding_service.register_bindings(registry, active_skill_registry.list_skills())

    def memory_retrieve_node(state: WorkflowGraphState) -> WorkflowGraphState:
        if active_memory_agent is None:
            return {}
        memories = active_memory_agent.retrieve(state["user_input"])
        memory_context = active_memory_agent.format_memories(memories)
        base_context = state.get("conversation_context", "")
        conversation_context = (
            f"{base_context}\n\n{memory_context}".strip()
            if memory_context
            else base_context
        )
        return {
            "base_conversation_context": base_context,
            "conversation_context": conversation_context,
            "retrieved_memories": memories,
            "events": _append_event(
                state,
                active_memory_agent.name,
                "retrieved",
                {
                    "retrieved_count": len(memories),
                    "memory_ids": [memory.memory_id for memory in memories],
                },
            ),
        }

    def skill_retrieve_node(state: WorkflowGraphState) -> WorkflowGraphState:
        if active_skill_registry is None:
            return {}
        catalog_skills = active_skill_registry.list_enabled_skills()
        skills_context = active_skill_registry.format_catalog_for_prompt()
        base_context = state.get("conversation_context", "")
        conversation_context = (
            f"{base_context}\n\n{skills_context}".strip()
            if skills_context
            else base_context
        )
        return {
            "conversation_context": conversation_context,
            "loaded_skills": catalog_skills,
            "events": _append_event(
                state,
                "skills",
                "loaded",
                {
                    "catalog_count": len(catalog_skills),
                    "skill_ids": [skill.skill_id for skill in catalog_skills],
                },
            ),
        }

    def supervisor_node(state: WorkflowGraphState) -> WorkflowGraphState:
        decision = supervisor.classify_intent(
            state["user_input"],
            conversation_context=state.get("conversation_context", ""),
        )
        conversation_context = state.get("conversation_context", "")
        selected_skill_id = _skill_id_from_tool_name(decision.required_tool)
        selected_skill_context = (
            active_skill_registry.format_skill_detail_for_prompt(selected_skill_id)
            if active_skill_registry is not None and selected_skill_id
            else ""
        )
        if selected_skill_context:
            conversation_context = f"{conversation_context}\n\n{selected_skill_context}".strip()
        return {
            "conversation_context": conversation_context,
            "intent": decision.intent,
            "task_kind": decision.task_kind,
            "execution_mode": decision.execution_mode,
            "need_memory": decision.need_memory,
            "required_tool": decision.required_tool,
            "should_plan": decision.should_plan,
            "requires_confirmation": decision.requires_confirmation,
            "risk_level": decision.risk_level,
            "route_confidence": decision.confidence,
            "direct_answer": supervisor.direct_answer(
                state["user_input"],
                conversation_context=state.get("conversation_context", ""),
                intent=decision.intent,
                task_kind=decision.task_kind,
            )
            if decision.execution_mode == "direct_answer"
            else "",
            "events": _append_event(
                state,
                supervisor.name,
                "completed",
                {
                    "intent": decision.intent,
                    "task_kind": decision.task_kind,
                    "execution_mode": decision.execution_mode,
                    "need_memory": decision.need_memory,
                    "need_tools": decision.need_tools,
                    "required_tool": decision.required_tool,
                    "should_plan": decision.should_plan,
                    "requires_confirmation": decision.requires_confirmation,
                    "risk_level": decision.risk_level,
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                    "selected_skill_id": selected_skill_id,
                },
            )
        }

    def route_after_supervisor(state: WorkflowGraphState) -> str:
        execution_mode = state.get("execution_mode", "direct_answer")
        if state.get("required_tool") in {"knowledge", "wiki_get_page"}:
            return "knowledge"
        if execution_mode == "plan_and_execute":
            return "planner"
        if execution_mode == "tool_call":
            return "direct_tool"
        if execution_mode == "clarification":
            return "clarification"
        return "direct_answer"

    def direct_answer_node(state: WorkflowGraphState) -> WorkflowGraphState:
        final_result = supervisor.finalize(
            FinalResult(
                answer=state.get("direct_answer", ""),
                sources=[],
                reflection=ReflectionResult(
                    passed=True,
                    issues=[],
                    suggested_fix="",
                    need_retry=False,
                ),
            )
        )
        return {
            "final_result": final_result,
            "events": _append_event(
                state,
                supervisor.name,
                "direct_answer",
                {"status": "finalized"},
            ),
        }

    def clarification_node(state: WorkflowGraphState) -> WorkflowGraphState:
        final_result = supervisor.finalize(
            FinalResult(
                answer=supervisor.clarification_answer(),
                sources=[],
                reflection=ReflectionResult(
                    passed=True,
                    issues=[],
                    suggested_fix="",
                    need_retry=False,
                ),
            )
        )
        return {
            "final_result": final_result,
            "events": _append_event(
                state,
                supervisor.name,
                "clarification",
                {"status": "waiting_for_user"},
            ),
        }

    def planner_node(state: WorkflowGraphState) -> WorkflowGraphState:
        plan = planner.plan(
            state["user_input"],
            conversation_context=state.get("conversation_context", ""),
        )
        return {
            "plan": plan,
            "events": _append_event(state, planner.name, "completed", plan.model_dump()),
        }

    def search_node(state: WorkflowGraphState) -> WorkflowGraphState:
        plan = state["plan"]
        tool_request = searcher.build_tool_request(plan)
        return {
            "tool_request": tool_request,
            "events": _append_event(
                state,
                searcher.name,
                "completed",
                tool_request,
            ),
        }

    def knowledge_node(state: WorkflowGraphState) -> WorkflowGraphState:
        plan = state.get("plan")
        if plan is None:
            plan = ExecutionPlan(
                goal=state["user_input"],
                steps=[
                    PlanStep(
                        step_id="knowledge-1",
                        description="Retrieve relevant pages from the local knowledge base.",
                        agent="knowledge",
                        expected_output="Relevant wiki pages, snippets, and relevance metadata.",
                    ),
                    PlanStep(
                        step_id="write-1",
                        description="Write the answer from gathered knowledge base pages.",
                        agent="writer",
                        expected_output="Markdown answer grounded in local knowledge.",
                    ),
                ],
                required_agents=["knowledge", "tool", "writer", "reflection"],
                expected_output="A source-aware answer grounded in the local knowledge base.",
                risk_points=[
                    "Knowledge base results may be incomplete if documents were not imported."
                ],
            )
        tool_name = state.get("required_tool", "knowledge")
        query = state["user_input"]
        if tool_name == "wiki_get_page":
            query = _extract_wiki_slug_from_input(state["user_input"])
        tool_request = knowledge_agent.build_tool_request(
            plan,
            tool_name=tool_name,
            query=query,
        )
        return {
            "plan": plan,
            "tool_request": tool_request,
            "events": _append_event(
                state,
                knowledge_agent.name,
                "completed",
                tool_request,
            ),
        }

    def direct_tool_node(state: WorkflowGraphState) -> WorkflowGraphState:
        tool_name = state.get("required_tool", "search")
        if not registry.has(tool_name):
            tool_name = "search"
        plan = ExecutionPlan(
            goal=state["user_input"],
            steps=[
                PlanStep(
                    step_id="tool-1",
                    description=f"Call {tool_name} tool directly.",
                    agent="tool",
                    expected_output="Relevant external results.",
                ),
                PlanStep(
                    step_id="write-1",
                    description="Write the answer from gathered tool results.",
                    agent="writer",
                    expected_output="Markdown answer.",
                ),
            ],
            required_agents=["tool", "writer", "reflection"],
            expected_output="A source-aware answer.",
            risk_points=[
                "Direct tool-call route skips planner; answer quality depends on tool results."
            ],
        )
        tool_result = tool_agent.invoke(
            tool_name,
            _tool_input_for_direct_call(tool_name, state["user_input"], registry),
        )
        sources, retrieval_diagnostic = _sources_and_retrieval_diagnostic(tool_result)
        pending_confirmation = _pending_confirmation_from_tool_result(tool_result)
        event_output = {
            "tool_name": tool_name,
            "source_count": len(sources),
            "route": "direct_tool_call",
        }
        if not isinstance(tool_result, list):
            event_output["tool_result"] = tool_result
        if retrieval_diagnostic:
            event_output["retrieval_diagnostic"] = retrieval_diagnostic
        return {
            "plan": plan,
            "sources": sources,
            "tool_result": {} if isinstance(tool_result, list) else tool_result,
            "pending_confirmation": pending_confirmation,
            "events": _append_event(
                state,
                tool_agent.name,
                "completed",
                event_output,
            ),
        }

    def tool_node(state: WorkflowGraphState) -> WorkflowGraphState:
        tool_request = state["tool_request"]
        tool_result = tool_agent.invoke(tool_request["tool_name"], tool_request["query"])
        sources, retrieval_diagnostic = _sources_and_retrieval_diagnostic(tool_result)
        pending_confirmation = _pending_confirmation_from_tool_result(tool_result)
        event_output = {
            "tool_name": tool_request["tool_name"],
            "source_count": len(sources),
        }
        if not isinstance(tool_result, list):
            event_output["tool_result"] = tool_result
        if retrieval_diagnostic:
            event_output["retrieval_diagnostic"] = retrieval_diagnostic
        return {
            "sources": sources,
            "tool_result": {} if isinstance(tool_result, list) else tool_result,
            "pending_confirmation": pending_confirmation,
            "events": _append_event(
                state,
                tool_agent.name,
                "completed",
                event_output,
            ),
        }

    def route_after_tool(state: WorkflowGraphState) -> str:
        if state.get("pending_confirmation"):
            return "await_confirmation"
        return "writer"

    def await_confirmation_node(state: WorkflowGraphState) -> WorkflowGraphState:
        return {
            "events": _append_event(
                state,
                supervisor.name,
                "await_confirmation",
                state.get("pending_confirmation", {}),
            )
        }

    def writer_node(state: WorkflowGraphState) -> WorkflowGraphState:
        plan = state["plan"]
        sources = state.get("sources", [])
        retrieval_diagnostic = state.get("tool_result", {}).get("retrieval_diagnostic", {})
        draft_answer = (
            writer.write_retrieval_diagnostic(retrieval_diagnostic)
            if not sources and retrieval_diagnostic
            else writer.write(
                plan,
                sources,
                conversation_context=state.get("conversation_context", ""),
            )
        )
        return {
            "draft_answer": draft_answer,
            "events": _append_event(
                state,
                writer.name,
                "completed",
                {"answer_length": len(draft_answer)},
            ),
        }

    def reflection_node(state: WorkflowGraphState) -> WorkflowGraphState:
        reflection = reflector.reflect(
            state["user_input"],
            state.get("draft_answer", ""),
            state.get("sources", []),
            conversation_context=state.get("conversation_context", ""),
        )
        return {
            "reflection": reflection,
            "events": _append_event(
                state,
                reflector.name,
                "completed",
                reflection.model_dump(),
            ),
        }

    def finalize_node(state: WorkflowGraphState) -> WorkflowGraphState:
        final_result = supervisor.finalize(
            FinalResult(
                answer=state.get("draft_answer", ""),
                sources=state.get("sources", []),
                reflection=state["reflection"],
            )
        )
        return {
            "final_result": final_result,
            "events": _append_event(
                state,
                supervisor.name,
                "completed",
                {"status": "finalized"},
            ),
        }

    def memory_update_node(state: WorkflowGraphState) -> WorkflowGraphState:
        if active_memory_agent is None:
            return {}
        final_result = state.get("final_result")
        answer = final_result.answer if final_result is not None else state.get("draft_answer", "")
        candidates = active_memory_agent.consolidate(
            state["user_input"],
            answer,
            conversation_context=state.get("base_conversation_context", ""),
        )
        validation_results = [
            active_memory_agent.validate(candidate).model_dump()
            for candidate in candidates
        ]
        saved = active_memory_agent.update(candidates)
        return {
            "events": _append_event(
                state,
                active_memory_agent.name,
                "updated",
                {
                    "candidate_count": len(candidates),
                    "saved_count": len(saved),
                    "validations": validation_results,
                    "memory_ids": [memory.memory_id for memory in saved],
                },
            )
        }

    graph = StateGraph(WorkflowGraphState)
    if active_memory_agent is not None:
        graph.add_node("memory_retrieve", memory_retrieve_node)
    if active_skill_registry is not None:
        graph.add_node("skill_retrieve", skill_retrieve_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("planner", planner_node)
    graph.add_node("search", search_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("direct_tool", direct_tool_node)
    graph.add_node("tool", tool_node)
    graph.add_node("await_confirmation", await_confirmation_node)
    graph.add_node("writer", writer_node)
    graph.add_node("reflection", reflection_node)
    graph.add_node("finalize", finalize_node)
    if active_memory_agent is not None:
        graph.add_node("memory_update", memory_update_node)

    if active_memory_agent is not None:
        graph.add_edge(START, "memory_retrieve")
        if active_skill_registry is not None:
            graph.add_edge("memory_retrieve", "skill_retrieve")
            graph.add_edge("skill_retrieve", "supervisor")
        else:
            graph.add_edge("memory_retrieve", "supervisor")
    elif active_skill_registry is not None:
        graph.add_edge(START, "skill_retrieve")
        graph.add_edge("skill_retrieve", "supervisor")
    else:
        graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "direct_answer": "direct_answer",
            "clarification": "clarification",
            "planner": "planner",
            "knowledge": "knowledge",
            "direct_tool": "direct_tool",
        },
    )
    if active_memory_agent is not None:
        graph.add_edge("direct_answer", "memory_update")
        graph.add_edge("clarification", "memory_update")
    else:
        graph.add_edge("direct_answer", END)
        graph.add_edge("clarification", END)
    graph.add_edge("planner", "search")
    graph.add_edge("search", "tool")
    graph.add_edge("knowledge", "tool")
    graph.add_conditional_edges(
        "direct_tool",
        route_after_tool,
        {
            "await_confirmation": "await_confirmation",
            "writer": "writer",
        },
    )
    graph.add_conditional_edges(
        "tool",
        route_after_tool,
        {
            "await_confirmation": "await_confirmation",
            "writer": "writer",
        },
    )
    graph.add_edge("await_confirmation", END)
    graph.add_edge("writer", "reflection")
    graph.add_edge("reflection", "finalize")
    if active_memory_agent is not None:
        graph.add_edge("finalize", "memory_update")
        graph.add_edge("memory_update", END)
    else:
        graph.add_edge("finalize", END)

    return graph.compile()


def _initial_state(
    task_id: str,
    user_input: str,
    conversation_context: str = "",
) -> WorkflowGraphState:
    return WorkflowGraphState(
        task_id=task_id,
        user_input=user_input,
        conversation_context=conversation_context,
        base_conversation_context=conversation_context,
        retrieved_memories=[],
        loaded_skills=[],
        events=[],
    )


def _workflow_result_from_state(
    state: WorkflowGraphState,
) -> WorkflowResult:
    return WorkflowResult(
        task_id=state["task_id"],
        user_input=state["user_input"],
        conversation_context=state.get("conversation_context", ""),
        plan=state.get("plan"),
        sources=state.get("sources", []),
        tool_result=state.get("tool_result", {}),
        pending_confirmation=state.get("pending_confirmation", {}),
        draft_answer=state.get("draft_answer", ""),
        final_result=state.get("final_result"),
        events=state.get("events", []),
    )


def stream_workflow_events(
    user_input: str,
    llm_client: LLMClient | None = None,
    use_configured_llm: bool = False,
    use_configured_search: bool = False,
    conversation_context: str = "",
    memory_agent: MemoryAgent | None = None,
    enable_memory: bool = False,
    skill_registry: LocalSkillRegistry | None = None,
    enable_skills: bool = False,
    skill_tool_binding_service: SkillToolBindingService | None = None,
):
    task_id = str(uuid4())
    graph = build_workflow_graph(
        llm_client=llm_client,
        use_configured_llm=use_configured_llm,
        use_configured_search=use_configured_search,
        memory_agent=memory_agent,
        enable_memory=enable_memory,
        skill_registry=skill_registry,
        enable_skills=enable_skills,
        skill_tool_binding_service=skill_tool_binding_service,
    )
    current_state = _initial_state(task_id, user_input, conversation_context)
    emitted_event_count = 0

    yield {
        "type": "workflow_started",
        "task_id": task_id,
        "user_input": user_input,
    }

    for chunk in graph.stream(current_state, stream_mode="updates"):
        for update in chunk.values():
            current_state.update(update)
            events = current_state.get("events", [])
            for event in events[emitted_event_count:]:
                yield {
                    "type": "agent_event",
                    "task_id": task_id,
                    "event": event,
                }
            emitted_event_count = len(events)

    yield {
        "type": "workflow_completed",
        "task_id": task_id,
        "result": _workflow_result_from_state(current_state),
    }


def run_workflow(
    user_input: str,
    llm_client: LLMClient | None = None,
    use_configured_llm: bool = False,
    use_configured_search: bool = False,
    conversation_context: str = "",
    memory_agent: MemoryAgent | None = None,
    enable_memory: bool = False,
    skill_registry: LocalSkillRegistry | None = None,
    enable_skills: bool = False,
    skill_tool_binding_service: SkillToolBindingService | None = None,
) -> WorkflowResult:
    task_id = str(uuid4())
    graph = build_workflow_graph(
        llm_client=llm_client,
        use_configured_llm=use_configured_llm,
        use_configured_search=use_configured_search,
        memory_agent=memory_agent,
        enable_memory=enable_memory,
        skill_registry=skill_registry,
        enable_skills=enable_skills,
        skill_tool_binding_service=skill_tool_binding_service,
    )
    final_state = graph.invoke(_initial_state(task_id, user_input, conversation_context))

    return _workflow_result_from_state(final_state)
