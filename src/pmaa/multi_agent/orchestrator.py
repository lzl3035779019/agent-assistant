from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Iterator
from uuid import uuid4

from pmaa.agents.memory import MemoryAgent as LegacyMemoryAgent
from pmaa.agents.reflection import ReflectionAgent
from pmaa.agents.writer import WriterAgent
from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage, create_llm_client
from pmaa.multi_agent.agents.catalog import build_default_agent_registry
from pmaa.multi_agent.blackboard import InMemoryBlackboard
from pmaa.multi_agent.contracts import (
    AgentMessage,
    AgentMessageType,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from pmaa.multi_agent.registry import AgentRegistry
from pmaa.multi_agent.runtime import CentralAgentRuntime
from pmaa.multi_agent.supervisor import HierarchicalSupervisor, SupervisorDecision
from pmaa.schemas.task import (
    AgentEvent,
    ExecutionPlan,
    FinalResult,
    PlanStep,
    ReflectionResult,
    Source,
)
from pmaa.tools.factory import (
    SearchTool,
    create_calendar_tool,
    create_github_monitor_tool,
    create_interest_topic_tool,
    create_knowledge_tool,
    create_search_tool,
)
from pmaa.tools.calendar_tool import CalendarTool
from pmaa.tools.registry import ToolRegistry
from pmaa.storage.monitor_store import SQLiteMonitorStore
from pmaa.storage.interest_topic_store import SQLiteInterestTopicStore
from pmaa.workflow.state import WorkflowResult


SUCCESS_STATUSES = {AgentStatus.COMPLETED, AgentStatus.PARTIAL}


class MultiAgentOrchestrator:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        supervisor: HierarchicalSupervisor,
        runtime: CentralAgentRuntime,
        llm_client: LLMClient | None = None,
        knowledge_tool: SearchTool | None = None,
        supervisor_tools: ToolRegistry | None = None,
        max_delegation_rounds: int = 3,
    ) -> None:
        self.registry = registry
        self.supervisor = supervisor
        self.runtime = runtime
        self.llm_client = llm_client
        self.knowledge_tool = knowledge_tool
        self.supervisor_tools = supervisor_tools or ToolRegistry()
        self.max_delegation_rounds = max_delegation_rounds
        self.writer = WriterAgent(llm_client)
        self.reflection = ReflectionAgent(llm_client)

    def run(
        self,
        user_input: str,
        conversation_context: str = "",
        assigned_agent: str = "",
    ) -> WorkflowResult:
        completed: WorkflowResult | None = None
        for event in self.stream(
            user_input,
            conversation_context,
            assigned_agent=assigned_agent,
        ):
            if event.get("type") == "workflow_completed":
                completed = event["result"]
        if completed is None:
            raise RuntimeError("Multi-agent workflow ended without a result.")
        return completed

    def run_system_agent_task(
        self,
        *,
        agent_id: str,
        objective: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, AgentResult]:
        """Run an explicitly assigned system task through the central runtime.

        Scheduled jobs do not need intent routing, but they must still use the
        same Supervisor-owned Blackboard and delegation protocol as user tasks.
        """
        spec = self.registry.get_spec(agent_id)
        root_task_id = str(uuid4())
        trace_id = uuid4().hex
        events: list[AgentEvent] = []
        task = AgentTask(
            trace_id=trace_id,
            parent_task_id=root_task_id,
            assigned_to=agent_id,
            objective=objective,
            context=context or {},
            allowed_tools=spec.allowed_tools,
            expected_output="返回结构化系统任务结果给 Supervisor。",
            max_retries=spec.max_retries,
        )
        results = self._consume(self._execute_plan(root_task_id, [task], events))
        return self._consume(
            self._resolve_delegations(root_task_id, results, events)
        )

    def stream(
        self,
        user_input: str,
        conversation_context: str = "",
        *,
        assigned_agent: str = "",
    ) -> Iterator[dict[str, Any]]:
        root_task_id = str(uuid4())
        trace_id = uuid4().hex
        events: list[AgentEvent] = []
        yield {
            "type": "workflow_started",
            "task_id": root_task_id,
            "trace_id": trace_id,
            "user_input": user_input,
            "architecture": "hierarchical_multi_agent",
        }

        decision = (
            self._assigned_agent_decision(assigned_agent, user_input)
            if assigned_agent
            else self.supervisor.analyze(user_input, conversation_context)
        )
        decision = self._bind_trace(decision, trace_id)
        supervisor_event = self._event(
            root_task_id,
            "supervisor",
            "decision_completed",
            output=decision.model_dump(mode="json"),
        )
        events.append(supervisor_event)
        yield self._stream_event(root_task_id, supervisor_event)

        results: dict[str, AgentResult] = {}
        sources: list[Source] = []
        pending_confirmation: dict[str, Any] = {}

        if decision.mode == "direct_answer":
            answer = self.supervisor.direct_answer(user_input, decision.intent)
        elif decision.mode == "clarification":
            answer = "请补充你希望完成的具体目标、范围或期望输出。"
        elif decision.mode == "tool":
            answer, sources, tool_event = self._run_supervisor_tool(
                root_task_id,
                user_input,
                conversation_context,
                decision,
            )
            events.append(tool_event)
            yield self._stream_event(root_task_id, tool_event)
        else:
            results = yield from self._execute_plan(
                root_task_id,
                decision.tasks,
                events,
            )
            results = yield from self._resolve_delegations(
                root_task_id,
                results,
                events,
            )
            sources = self._sources_from_results(results.values())
            pending_confirmation = self._pending_confirmation(results.values())
            answer = self._synthesize(
                user_input,
                conversation_context,
                results,
                sources,
                pending_confirmation,
            )

        memory_result = yield from self._consolidate_memory(
            root_task_id,
            trace_id,
            user_input,
            conversation_context,
            answer,
            events,
        )
        if memory_result is not None:
            results[memory_result.task_id] = memory_result

        reflection = self._reflect(user_input, answer, sources, results, pending_confirmation)
        final_result = FinalResult(
            answer=answer,
            sources=sources,
            reflection=reflection,
        )
        workflow_result = WorkflowResult(
            task_id=root_task_id,
            user_input=user_input,
            conversation_context=conversation_context,
            plan=self._legacy_plan(user_input, decision),
            sources=sources,
            tool_result={
                "architecture": "hierarchical_multi_agent",
                "trace_id": trace_id,
                "supervisor_decision": decision.model_dump(mode="json"),
                "agent_results": {
                    task_id: result.model_dump(mode="json")
                    for task_id, result in results.items()
                },
            },
            pending_confirmation=pending_confirmation,
            draft_answer=answer,
            final_result=final_result,
            events=events,
        )
        yield {
            "type": "workflow_completed",
            "task_id": root_task_id,
            "trace_id": trace_id,
            "result": workflow_result,
        }

    def _assigned_agent_decision(
        self,
        agent_id: str,
        objective: str,
    ) -> SupervisorDecision:
        """Create a validated decision for an internal, explicitly routed task."""
        spec = self.registry.get_spec(agent_id)
        if not spec.enabled:
            raise ValueError(f"Agent is disabled: {agent_id}")
        return self.supervisor.validate_decision(
            SupervisorDecision(
                intent=f"system_{agent_id}",
                mode="delegate",
                tasks=[
                    AgentTask(
                        assigned_to=agent_id,
                        objective=objective,
                        allowed_tools=spec.allowed_tools,
                        expected_output="返回结构化系统任务结果给 Supervisor。",
                        max_retries=spec.max_retries,
                    )
                ],
                confidence=1,
                reason=f"系统任务已显式委派给 {spec.name}。",
            )
        )

    def _execute_plan(
        self,
        root_task_id: str,
        tasks: list[AgentTask],
        events: list[AgentEvent],
    ) -> Iterator[dict[str, Any]]:
        pending = {task.task_id: task for task in tasks}
        results: dict[str, AgentResult] = {}
        while pending:
            ready = [
                task
                for task in pending.values()
                if all(
                    dependency in results
                    and results[dependency].status in SUCCESS_STATUSES
                    for dependency in task.depends_on
                )
            ]
            if not ready:
                for task in pending.values():
                    result = AgentResult(
                        task_id=task.task_id,
                        agent_id=task.assigned_to,
                        status=AgentStatus.FAILED,
                        summary="任务依赖未满足。",
                        errors=["Blocked by failed or missing dependencies."],
                    )
                    results[task.task_id] = result
                    event = self._result_event(root_task_id, task, result)
                    events.append(event)
                    yield self._stream_event(root_task_id, event)
                break
            for task in ready:
                pending.pop(task.task_id)
            batch_results = yield from self._dispatch_batch(root_task_id, ready, events)
            results.update(batch_results)
        return results

    def _dispatch_batch(
        self,
        root_task_id: str,
        tasks: list[AgentTask],
        events: list[AgentEvent],
    ) -> Iterator[dict[str, Any]]:
        for task in tasks:
            event = self._event(
                root_task_id,
                task.assigned_to,
                "task_started",
                input={
                    "task_id": task.task_id,
                    "objective": task.objective,
                    "depends_on": task.depends_on,
                },
            )
            events.append(event)
            yield self._stream_event(root_task_id, event)

        results: dict[str, AgentResult] = {}
        workers = min(self.runtime.max_concurrency, max(1, len(tasks)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_task = {
                executor.submit(self.runtime.dispatch, task): task for task in tasks
            }
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = AgentResult(
                        task_id=task.task_id,
                        agent_id=task.assigned_to,
                        status=AgentStatus.FAILED,
                        summary="Agent 调度失败。",
                        errors=[str(exc)],
                    )
                results[task.task_id] = result
                event = self._result_event(root_task_id, task, result)
                events.append(event)
                yield self._stream_event(root_task_id, event)
        return results

    def _resolve_delegations(
        self,
        root_task_id: str,
        results: dict[str, AgentResult],
        events: list[AgentEvent],
    ) -> Iterator[dict[str, Any]]:
        seen_messages: set[str] = set()
        for _round in range(self.max_delegation_rounds):
            waiting_tasks = [
                self.runtime.blackboard.get_task(task_id)
                for task_id, result in results.items()
                if result.status == AgentStatus.WAITING_DEPENDENCY
            ]
            if not waiting_tasks:
                break

            delegated: list[AgentTask] = []
            for parent in waiting_tasks:
                for message in self.runtime.blackboard.list_messages(parent.task_id):
                    if (
                        message.message_type != AgentMessageType.DELEGATION_REQUEST
                        or message.message_id in seen_messages
                    ):
                        continue
                    seen_messages.add(message.message_id)
                    child = self._task_from_delegation(parent, message)
                    if child is not None:
                        delegated.append(child)
                    elif self._resolve_supervisor_tool(
                        root_task_id,
                        parent,
                        message,
                        events,
                    ):
                        yield self._stream_event(root_task_id, events[-1])
                    else:
                        event = self._event(
                            root_task_id,
                            "supervisor",
                            "delegation_unresolved",
                            output={
                                "parent_task_id": parent.task_id,
                                "capability": message.content.get("target_capability"),
                            },
                        )
                        events.append(event)
                        yield self._stream_event(root_task_id, event)

            if delegated:
                delegated_results = yield from self._dispatch_batch(
                    root_task_id, delegated, events
                )
                results.update(delegated_results)

            resumed_any = False
            for parent in waiting_tasks:
                event = self._event(
                    root_task_id,
                    parent.assigned_to,
                    "task_resumed",
                    input={"task_id": parent.task_id},
                )
                events.append(event)
                yield self._stream_event(root_task_id, event)
                resumed = self.runtime.dispatch(parent)
                results[parent.task_id] = resumed
                resumed_any = True
                result_event = self._result_event(root_task_id, parent, resumed)
                events.append(result_event)
                yield self._stream_event(root_task_id, result_event)
            if not delegated and not resumed_any:
                break
        return results

    def _resolve_supervisor_tool(
        self,
        root_task_id: str,
        parent: AgentTask,
        message: AgentMessage,
        events: list[AgentEvent],
    ) -> bool:
        capability = str(message.content.get("target_capability", ""))
        if not self.supervisor_tools.has(capability):
            return False
        request = dict(message.content.get("context") or {})
        request["objective"] = str(message.content.get("objective") or capability)
        try:
            output = self.supervisor_tools.call(capability, request)
            event_type = "supervisor_tool_completed"
        except Exception as exc:
            output = {
                "status": "failed",
                "events": [],
                "reason": str(exc),
            }
            event_type = "supervisor_tool_failed"
        artifacts = self.runtime.blackboard.get_artifacts(parent.task_id)
        artifact_name = capability
        if artifact_name in artifacts:
            artifact_name = f"{capability}:{message.message_id}"
        self.runtime.blackboard.put_artifact(parent.task_id, artifact_name, output)
        event = self._event(
            root_task_id,
            "supervisor",
            event_type,
            output={
                "parent_task_id": parent.task_id,
                "tool": capability,
                "status": output.get("status") if isinstance(output, dict) else "ok",
            },
        )
        events.append(event)
        return True

    def _task_from_delegation(
        self,
        parent: AgentTask,
        message: AgentMessage,
    ) -> AgentTask | None:
        capability = str(message.content.get("target_capability", ""))
        spec = next(
            (
                item
                for item in self.registry.list_specs()
                if capability == item.agent_id or capability in item.capabilities
            ),
            None,
        )
        if spec is None:
            return None
        objective = str(message.content.get("objective") or capability)
        child_context = dict(message.content.get("context") or {})
        if capability.startswith("memory."):
            child_context.update({"mode": "retrieve", "query": objective})
        elif capability == "email.today_unread":
            child_context["email_request"] = {
                "action": "list_recent",
                "limit": 10,
                "unread_only": True,
                "today_only": True,
            }
        return AgentTask(
            trace_id=parent.trace_id,
            parent_task_id=parent.task_id,
            assigned_to=spec.agent_id,
            objective=objective,
            context=child_context,
            allowed_tools=spec.allowed_tools,
            expected_output="返回结构化依赖结果给 Supervisor。",
            max_retries=spec.max_retries,
        )

    def _run_supervisor_tool(
        self,
        root_task_id: str,
        user_input: str,
        conversation_context: str,
        decision: SupervisorDecision,
    ) -> tuple[str, list[Source], AgentEvent]:
        sources: list[Source] = []
        error = ""
        if decision.direct_tool in {"knowledge", "wiki_get_page"}:
            if self.knowledge_tool is None:
                error = "GBrain 知识库工具当前不可用。"
            else:
                try:
                    query = str(decision.tool_arguments.get("query") or user_input)
                    sources = self.knowledge_tool(query)
                except Exception as exc:
                    error = str(exc)
        if sources:
            plan = self._source_plan(user_input, "supervisor_knowledge")
            answer = self.writer.write(plan, sources, conversation_context)
        else:
            answer = error or "知识库中没有检索到足够的可引用内容。"
        event = self._event(
            root_task_id,
            "supervisor",
            "tool_completed" if not error else "tool_failed",
            output={
                "tool": decision.direct_tool,
                "source_count": len(sources),
                "error": error,
            },
        )
        return answer, sources, event

    def _synthesize(
        self,
        user_input: str,
        conversation_context: str,
        results: dict[str, AgentResult],
        sources: list[Source],
        pending_confirmation: dict[str, Any],
    ) -> str:
        if pending_confirmation:
            return "相关内容已准备完成，等待你确认后执行。"
        primary = [
            result
            for result in results.values()
            if result.agent_id != "memory" and result.status != AgentStatus.FAILED
        ]
        for result in primary:
            if isinstance(result.output.get("brief"), str):
                return result.output["brief"]
        for result in primary:
            if result.agent_id == "information_monitor":
                return self._monitor_answer(result)
        if sources:
            return self.writer.write(
                self._source_plan(user_input, "multi_agent"),
                sources,
                conversation_context,
            )
        if not primary:
            errors = [error for result in results.values() for error in result.errors]
            return "任务未能完成。" + (f"原因：{'；'.join(errors)}" if errors else "")
        payload = [
            {
                "agent": result.agent_id,
                "summary": result.summary,
                "output": result.output,
                "confidence": result.confidence,
            }
            for result in primary
        ]
        if self.llm_client is not None:
            try:
                return self.llm_client.complete_text(
                    [
                        LLMMessage(
                            role="system",
                            content=(
                                "你是 PMAA Supervisor 的结果汇总模块。基于子 Agent 的结构化"
                                "结果回答用户，不得声称未执行的工具已经执行。使用中文 Markdown。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=f"用户请求：{user_input}\n子 Agent 结果：{payload}",
                        ),
                    ]
                )
            except LLMClientError:
                pass
        return "\n\n".join(
            f"## {item['agent']}\n\n{item['summary']}\n\n{item['output']}"
            for item in payload
        )

    @staticmethod
    def _monitor_answer(result: AgentResult) -> str:
        output = result.output
        changes = output.get("important_changes", [])
        baseline_count = int(output.get("baseline_created", 0) or 0)
        sections = ["# 信息监控结果"]
        if baseline_count:
            sections.append(
                f"已为 {baseline_count} 条监控规则建立首次基线；首次采集不会误报为新增变化。"
            )
        if not isinstance(changes, list) or not changes:
            sections.append("本轮没有发现需要提醒的重要变化。")
            return "\n\n".join(sections)
        sections.append("## 重要变化")
        for item in changes:
            if not isinstance(item, dict):
                sections.append(f"- {item}")
                continue
            change = item.get("change", {})
            if isinstance(change, dict):
                title = str(change.get("title") or change.get("url") or "监控更新")
                url = str(change.get("url", ""))
                label = f"[{title}]({url})" if url else title
            else:
                label = str(change)
            relevance = str(item.get("relevance", "")).strip()
            action = str(item.get("recommended_action", "")).strip()
            detail = "；".join(part for part in [relevance, action] if part)
            sections.append(f"- {label}" + (f"：{detail}" if detail else ""))
        return "\n\n".join(sections)

    def _consolidate_memory(
        self,
        root_task_id: str,
        trace_id: str,
        user_input: str,
        conversation_context: str,
        answer: str,
        events: list[AgentEvent],
    ) -> Iterator[dict[str, Any]]:
        try:
            spec = self.registry.get_spec("memory")
        except KeyError:
            return None
        task = AgentTask(
            trace_id=trace_id,
            parent_task_id=root_task_id,
            assigned_to="memory",
            objective="分析本轮会话并维护值得保存的长期记忆。",
            context={
                "mode": "consolidate",
                "user_input": user_input,
                "assistant_answer": answer,
                "conversation_context": conversation_context,
            },
            allowed_tools=spec.allowed_tools,
            expected_output="候选记忆、验证结果和保存记录。",
            max_retries=spec.max_retries,
        )
        batch = yield from self._dispatch_batch(root_task_id, [task], events)
        return batch.get(task.task_id)

    def _reflect(
        self,
        user_input: str,
        answer: str,
        sources: list[Source],
        results: dict[str, AgentResult],
        pending_confirmation: dict[str, Any],
    ) -> ReflectionResult:
        if pending_confirmation:
            return ReflectionResult(
                passed=True,
                issues=[],
                suggested_fix="等待用户确认。",
                need_retry=False,
            )
        failures = [
            result for result in results.values() if result.status == AgentStatus.FAILED
        ]
        if failures and not answer.strip():
            return ReflectionResult(
                passed=False,
                issues=[error for result in failures for error in result.errors],
                suggested_fix="检查失败 Agent 的工具配置后重试。",
                need_retry=True,
            )
        if sources:
            return self.reflection.reflect(user_input, answer, sources)
        return ReflectionResult(
            passed=bool(answer.strip()),
            issues=[] if answer.strip() else ["Answer is empty."],
            suggested_fix="" if answer.strip() else "重新生成回答。",
            need_retry=not bool(answer.strip()),
        )

    def _sources_from_results(self, results) -> list[Source]:
        sources: list[Source] = []
        for result in results:
            raw_sources = result.output.get("sources", [])
            if isinstance(raw_sources, list):
                for raw in raw_sources:
                    try:
                        sources.append(Source.model_validate(raw))
                    except ValueError:
                        continue
        unique: dict[str, Source] = {}
        for source in sources:
            key = source.url.strip().lower() or source.title.strip().lower()
            if key and key not in unique:
                unique[key] = source
        return list(unique.values())

    @staticmethod
    def _pending_confirmation(results) -> dict[str, Any]:
        for result in results:
            pending = result.output.get("pending_action")
            if result.status == AgentStatus.WAITING_CONFIRMATION and isinstance(pending, dict):
                return pending
        return {}

    @staticmethod
    def _bind_trace(
        decision: SupervisorDecision,
        trace_id: str,
    ) -> SupervisorDecision:
        return decision.model_copy(
            update={
                "tasks": [
                    task.model_copy(update={"trace_id": trace_id})
                    for task in decision.tasks
                ]
            }
        )

    @staticmethod
    def _source_plan(goal: str, agent: str) -> ExecutionPlan:
        return ExecutionPlan(
            goal=goal,
            steps=[
                PlanStep(
                    step_id="synthesize-1",
                    description="基于子 Agent 证据生成回答。",
                    agent=agent,
                    expected_output="带来源引用的中文 Markdown。",
                )
            ],
            required_agents=[agent],
            expected_output="带来源引用的中文 Markdown。",
        )

    @staticmethod
    def _legacy_plan(
        goal: str,
        decision: SupervisorDecision,
    ) -> ExecutionPlan | None:
        if not decision.tasks:
            return None
        return ExecutionPlan(
            goal=goal,
            steps=[
                PlanStep(
                    step_id=task.task_id,
                    description=task.objective,
                    agent=task.assigned_to,
                    expected_output=task.expected_output,
                )
                for task in decision.tasks
            ],
            required_agents=list(dict.fromkeys(task.assigned_to for task in decision.tasks)),
            expected_output="Supervisor 汇总后的最终回答。",
        )

    @staticmethod
    def _event(
        task_id: str,
        agent: str,
        event_type: str,
        *,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
    ) -> AgentEvent:
        return AgentEvent(
            task_id=task_id,
            agent=agent,
            event_type=event_type,
            input=input or {},
            output=output or {},
            timestamp=datetime.now(UTC),
        )

    @staticmethod
    def _result_event(
        root_task_id: str,
        task: AgentTask,
        result: AgentResult,
    ) -> AgentEvent:
        return MultiAgentOrchestrator._event(
            root_task_id,
            task.assigned_to,
            "task_completed",
            output={
                "task_id": task.task_id,
                "status": result.status.value,
                "summary": result.summary,
                "confidence": result.confidence,
                "errors": result.errors,
            },
        )

    @staticmethod
    def _stream_event(task_id: str, event: AgentEvent) -> dict[str, Any]:
        return {"type": "agent_event", "task_id": task_id, "event": event}

    @staticmethod
    def _consume(iterator: Iterator[dict[str, Any]]) -> Any:
        while True:
            try:
                next(iterator)
            except StopIteration as completed:
                return completed.value


def create_default_orchestrator(
    *,
    llm_client: LLMClient | None = None,
    search_tool: SearchTool | None = None,
    knowledge_tool: SearchTool | None = None,
    calendar_tool: CalendarTool | None = None,
    monitor_store: SQLiteMonitorStore | None = None,
    interest_topic_store: SQLiteInterestTopicStore | None = None,
) -> MultiAgentOrchestrator:
    active_llm = llm_client if llm_client is not None else create_llm_client()
    active_search = search_tool if search_tool is not None else create_search_tool()
    active_knowledge = (
        knowledge_tool if knowledge_tool is not None else create_knowledge_tool()
    )
    memory = LegacyMemoryAgent(llm_client=active_llm)
    registry = build_default_agent_registry(
        search_tool=active_search,
        llm_client=active_llm,
        memory_agent=memory,
        monitor_store=monitor_store,
    )
    blackboard = InMemoryBlackboard()
    runtime = CentralAgentRuntime(registry, blackboard=blackboard)
    supervisor = HierarchicalSupervisor(
        registry,
        active_llm,
        knowledge_available=active_knowledge is not None,
    )
    supervisor_tools = ToolRegistry()
    supervisor_tools.register("calendar.read", calendar_tool or create_calendar_tool())
    supervisor_tools.register("github.read", create_github_monitor_tool())
    supervisor_tools.register(
        "interest_topics.read",
        create_interest_topic_tool(interest_topic_store),
    )
    return MultiAgentOrchestrator(
        registry=registry,
        supervisor=supervisor,
        runtime=runtime,
        llm_client=active_llm,
        knowledge_tool=active_knowledge,
        supervisor_tools=supervisor_tools,
    )


def run_multi_agent_workflow(
    user_input: str,
    conversation_context: str = "",
    assigned_agent: str = "",
) -> WorkflowResult:
    return create_default_orchestrator().run(
        user_input,
        conversation_context,
        assigned_agent=assigned_agent,
    )


def stream_multi_agent_workflow_events(
    user_input: str,
    conversation_context: str = "",
    assigned_agent: str = "",
) -> Iterator[dict[str, Any]]:
    yield from create_default_orchestrator().stream(
        user_input,
        conversation_context,
        assigned_agent=assigned_agent,
    )
