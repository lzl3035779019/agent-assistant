from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from typing_extensions import TypedDict

from pmaa.llm.client import LLMClient, LLMClientError, LLMMessage
from pmaa.multi_agent.contracts import AgentResult, AgentStatus, AgentTask
from pmaa.multi_agent.runtime import AgentExecutionContext
from pmaa.schemas.monitor import MonitorRule
from pmaa.storage.monitor_store import SQLiteMonitorStore


MANAGEMENT_ACTIONS = {"create_rule", "update_rule", "delete_rule", "list_rules"}


class InformationMonitorState(TypedDict, total=False):
    objective: str
    action: str
    rule_payload: dict[str, Any]
    provided_rules: list[dict[str, Any]]
    rules: list[MonitorRule]
    observations: list[dict[str, Any]]
    dependency_attempted: bool
    allowed_tools: list[str]
    execution_context: AgentExecutionContext
    waiting: bool
    requested_capabilities: list[str]
    comparisons: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    analysis: dict[str, Any]
    saved_snapshots: list[dict[str, Any]]
    management_result: dict[str, Any]
    errors: list[str]


class InformationMonitorGraphAgent:
    agent_id = "information_monitor"
    system_prompt = (
        "你是 Information Monitor Agent。你只监控用户指定的公司动态、招聘、新闻、"
        "GitHub 项目和技术博客，不监控论文。你需要比较本轮与历史快照，只报告新增或"
        "显著变化，并说明为什么与用户相关以及是否需要行动。"
    )

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        store: SQLiteMonitorStore | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.store = store or SQLiteMonitorStore()
        self.graph = self._build_graph()

    def __call__(
        self,
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> AgentResult:
        raw_observations = task.context.get("observations")
        observations, child_attempted = self._child_observations(task, context)
        tool_observations, tool_attempted = self._tool_observations(task, context)
        observations.extend(tool_observations)
        child_attempted = child_attempted or tool_attempted
        if isinstance(raw_observations, list):
            observations = [item for item in raw_observations if isinstance(item, dict)]
            child_attempted = True
        raw_rules = task.context.get("rules")
        state = self.graph.invoke(
            {
                "objective": task.objective,
                "action": str(task.context.get("action", "")),
                "rule_payload": (
                    dict(task.context.get("rule"))
                    if isinstance(task.context.get("rule"), dict)
                    else {}
                ),
                "provided_rules": (
                    [item for item in raw_rules if isinstance(item, dict)]
                    if isinstance(raw_rules, list)
                    else []
                ),
                "rules": [],
                "observations": observations,
                "dependency_attempted": child_attempted,
                "allowed_tools": task.allowed_tools,
                "execution_context": context,
                "waiting": False,
                "requested_capabilities": [],
                "comparisons": [],
                "changes": [],
                "analysis": {},
                "saved_snapshots": [],
                "management_result": {},
                "errors": [],
            }
        )
        action = state.get("action", "run_monitor")
        if state.get("waiting"):
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=AgentStatus.WAITING_DEPENDENCY,
                summary="已向 Supervisor 请求监控目标的公开信息证据。",
                output={
                    "requested_capabilities": state.get("requested_capabilities", []),
                    "rule_count": len(state.get("rules", [])),
                    "workflow": ["determine_action", "load_rules", "collect_evidence"],
                },
                confidence=0.82,
            )
        errors = state.get("errors", [])
        if action in MANAGEMENT_ACTIONS:
            failed = bool(errors)
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=AgentStatus.FAILED if failed else AgentStatus.COMPLETED,
                summary="监控规则操作失败。" if failed else "监控规则操作已完成。",
                output={
                    "action": action,
                    **state.get("management_result", {}),
                    "workflow": ["determine_action", "manage_rules"],
                },
                errors=errors,
                confidence=0.9 if not failed else 0.2,
            )
        analysis = state.get("analysis", {})
        important_changes = analysis.get("important_changes", [])
        partial = bool(errors)
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=AgentStatus.PARTIAL if partial else AgentStatus.COMPLETED,
            summary=(
                f"监控完成，发现 {len(important_changes)} 条重要变化。"
                if important_changes
                else "监控完成，本轮没有需要提醒的重要变化。"
            ),
            output={
                "rules": [rule.model_dump() for rule in state.get("rules", [])],
                "comparisons": state.get("comparisons", []),
                "important_changes": important_changes,
                "baseline_created": sum(
                    1 for item in state.get("comparisons", []) if item.get("baseline")
                ),
                "saved_snapshots": state.get("saved_snapshots", []),
                "workflow": [
                    "determine_action",
                    "load_rules",
                    "collect_evidence",
                    "compare_snapshots",
                    "analyze_changes",
                    "save_snapshots",
                    "finalize",
                ],
            },
            errors=errors,
            confidence=0.72 if partial else 0.88,
        )

    def _build_graph(self):
        graph = StateGraph(InformationMonitorState)
        graph.add_node("determine", self._determine_action)
        graph.add_node("manage", self._manage_rules)
        graph.add_node("load", self._load_rules)
        graph.add_node("collect", self._collect_evidence)
        graph.add_node("compare", self._compare_snapshots)
        graph.add_node("analyze", self._analyze_changes)
        graph.add_node("save", self._save_snapshots)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "determine")
        graph.add_conditional_edges(
            "determine",
            self._after_determine,
            {"manage": "manage", "load": "load"},
        )
        graph.add_edge("manage", END)
        graph.add_edge("load", "collect")
        graph.add_conditional_edges(
            "collect",
            self._after_collect,
            {"wait": END, "compare": "compare"},
        )
        graph.add_edge("compare", "analyze")
        graph.add_edge("analyze", "save")
        graph.add_edge("save", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _determine_action(self, state: InformationMonitorState) -> dict[str, Any]:
        state["execution_context"].report_progress("determining_monitor_action")
        action = state.get("action", "").strip()
        if not action:
            action = self._infer_action(state.get("objective", ""))
        if action == "analyze_changes":
            action = "run_monitor"
        return {"action": action}

    @staticmethod
    def _after_determine(state: InformationMonitorState) -> str:
        return "manage" if state.get("action") in MANAGEMENT_ACTIONS else "load"

    def _manage_rules(self, state: InformationMonitorState) -> dict[str, Any]:
        state["execution_context"].report_progress("managing_monitor_rules")
        action = state.get("action", "")
        payload = state.get("rule_payload", {})
        if action != "list_rules" and "monitor.store" not in state.get("allowed_tools", []):
            return {"errors": [f"{action} requires monitor.store permission."]}
        try:
            if action == "list_rules":
                rules = self.store.list_rules()
                return {
                    "management_result": {
                        "rules": [rule.model_dump() for rule in rules]
                    }
                }
            if action == "create_rule":
                rule = self._rule_from_payload(payload, state.get("objective", ""))
                saved = self.store.save_rule(rule)
                return {"management_result": {"rule": saved.model_dump()}}
            rule_id = str(payload.get("rule_id", "")).strip()
            if not rule_id:
                return {"errors": [f"{action} requires rule_id."]}
            if action == "delete_rule":
                deleted = self.store.delete_rule(rule_id)
                if not deleted:
                    return {"errors": [f"Monitor rule does not exist: {rule_id}"]}
                return {"management_result": {"deleted_rule_id": rule_id}}
            current = self.store.get_rule(rule_id)
            if current is None:
                return {"errors": [f"Monitor rule does not exist: {rule_id}"]}
            merged = current.model_dump()
            merged.update(payload)
            saved = self.store.save_rule(MonitorRule.model_validate(merged))
            return {"management_result": {"rule": saved.model_dump()}}
        except (ValidationError, ValueError) as exc:
            return {"errors": [str(exc)]}

    def _load_rules(self, state: InformationMonitorState) -> dict[str, Any]:
        state["execution_context"].report_progress("loading_monitor_rules")
        provided = state.get("provided_rules", [])
        rules: list[MonitorRule] = []
        errors: list[str] = []
        for raw_rule in provided:
            try:
                rules.append(MonitorRule.model_validate(raw_rule))
            except ValidationError as exc:
                errors.append(str(exc))
        if not rules:
            rules = self.store.list_rules(enabled_only=True)
        if not rules and self._has_specific_target(state.get("objective", "")):
            rules = [self._rule_from_payload({}, state.get("objective", ""))]
        if not rules:
            errors.append("没有可执行的监控规则，请先创建公司、招聘、GitHub 或技术博客规则。")
        return {"rules": rules, "errors": errors}

    def _collect_evidence(self, state: InformationMonitorState) -> dict[str, Any]:
        state["execution_context"].report_progress("collecting_monitor_evidence")
        rules = state.get("rules", [])
        if not rules:
            return {"waiting": False}
        if state.get("observations") or state.get("dependency_attempted"):
            return {"waiting": False}
        requested: list[str] = []
        context = state["execution_context"]
        for rule in rules:
            target_capability = (
                "github.read"
                if rule.target_type == "github"
                and "github.read" in state.get("allowed_tools", [])
                else "web_research"
            )
            context.request_delegation(
                target_capability=target_capability,
                objective=rule.query,
                reason=f"监控规则“{rule.name}”需要最新公开信息。",
                context={
                    "monitor_rule_id": rule.rule_id,
                    "monitor_target_type": rule.target_type,
                    "monitor_target": rule.target,
                },
            )
            requested.append(target_capability)
        return {"waiting": True, "requested_capabilities": requested}

    @staticmethod
    def _after_collect(state: InformationMonitorState) -> str:
        return "wait" if state.get("waiting") else "compare"

    def _compare_snapshots(self, state: InformationMonitorState) -> dict[str, Any]:
        state["execution_context"].report_progress("comparing_monitor_snapshots")
        rules = state.get("rules", [])
        observations = self._assign_observations(state.get("observations", []), rules)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            rule_id = str(observation.get("rule_id", ""))
            source = observation.get("source")
            if rule_id and isinstance(source, dict):
                grouped[rule_id].append(source)
        comparisons: list[dict[str, Any]] = []
        changes: list[dict[str, Any]] = []
        errors = list(state.get("errors", []))
        for rule in rules:
            current_items = self._deduplicate_items(grouped.get(rule.rule_id, []))
            previous = self.store.latest_snapshot(rule.rule_id)
            if not current_items:
                errors.append(f"监控规则“{rule.name}”没有获得可比较的证据。")
                comparisons.append(
                    {
                        "rule_id": rule.rule_id,
                        "rule_name": rule.name,
                        "baseline": previous is None,
                        "current_items": [],
                        "new_items": [],
                        "save_snapshot": False,
                    }
                )
                continue
            previous_by_key = {
                self._item_key(item): item for item in (previous.items if previous else [])
            }
            new_items = []
            updated_items = []
            if previous is not None:
                for item in current_items:
                    key = self._item_key(item)
                    previous_item = previous_by_key.get(key)
                    if previous_item is None:
                        new_items.append(item)
                    elif self._meaningfully_changed(
                        previous_item,
                        item,
                        target_type=rule.target_type,
                    ):
                        updated_items.append(item)
            comparison = {
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "target_type": rule.target_type,
                "baseline": previous is None,
                "previous_fingerprint": previous.fingerprint if previous else "",
                "current_fingerprint": self.store.fingerprint(current_items),
                "current_items": current_items,
                "new_items": new_items,
                "updated_items": updated_items,
                "save_snapshot": True,
            }
            comparisons.append(comparison)
            changes.extend(
                {
                    "rule_id": rule.rule_id,
                    "rule_name": rule.name,
                    "target_type": rule.target_type,
                    "change_type": "new_item",
                    "item": item,
                }
                for item in new_items
            )
            changes.extend(
                {
                    "rule_id": rule.rule_id,
                    "rule_name": rule.name,
                    "target_type": rule.target_type,
                    "change_type": "updated_item",
                    "item": item,
                }
                for item in updated_items
            )
        return {"comparisons": comparisons, "changes": changes, "errors": errors}

    def _analyze_changes(self, state: InformationMonitorState) -> dict[str, Any]:
        state["execution_context"].report_progress("analyzing_monitor_changes")
        changes = state.get("changes", [])
        if not changes:
            return {"analysis": {"important_changes": []}}
        fallback = {
            "important_changes": [
                {
                    "rule_id": item.get("rule_id", ""),
                    "change": item.get("item", {}),
                    "relevance": f"与监控目标“{item.get('rule_name', '')}”直接相关。",
                    "recommended_action": "查看来源并决定是否需要进一步行动。",
                    "confidence": 0.75,
                }
                for item in changes
            ]
        }
        if self.llm_client is None:
            return {"analysis": fallback}
        try:
            payload = self.llm_client.complete_json(
                [
                    LLMMessage(role="system", content=self.system_prompt),
                    LLMMessage(
                        role="system",
                        content=(
                            "只输出 JSON：{\"important_changes\":[{\"rule_id\":\"...\","
                            "\"change\":{},\"relevance\":\"...\","
                            "\"recommended_action\":\"...\",\"confidence\":0.0}]}。"
                            "过滤重复、低价值和无法验证的变化。"
                        ),
                    ),
                    LLMMessage(role="user", content=f"新增变化：{changes}"),
                ]
            )
            important = payload.get("important_changes")
            if isinstance(important, list):
                return {"analysis": {"important_changes": important}}
        except (LLMClientError, ValueError, TypeError):
            pass
        return {"analysis": fallback}

    def _save_snapshots(self, state: InformationMonitorState) -> dict[str, Any]:
        state["execution_context"].report_progress("saving_monitor_snapshots")
        rules = {rule.rule_id: rule for rule in state.get("rules", [])}
        saved: list[dict[str, Any]] = []
        errors = list(state.get("errors", []))
        if "monitor.store" not in state.get("allowed_tools", []):
            errors.append("Saving monitor snapshots requires monitor.store permission.")
            return {"saved_snapshots": [], "errors": errors}
        for comparison in state.get("comparisons", []):
            if not comparison.get("save_snapshot"):
                continue
            rule_id = str(comparison.get("rule_id", ""))
            rule = rules.get(rule_id)
            if rule is None:
                continue
            try:
                if self.store.get_rule(rule_id) is None:
                    self.store.save_rule(rule)
                snapshot = self.store.save_snapshot(
                    rule_id,
                    comparison.get("current_items", []),
                )
                saved.append(snapshot.model_dump())
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
        return {"saved_snapshots": saved, "errors": errors}

    @staticmethod
    def _finalize(state: InformationMonitorState) -> dict[str, Any]:
        return {}

    @staticmethod
    def _child_observations(
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> tuple[list[dict[str, Any]], bool]:
        snapshot = context.blackboard.snapshot()
        observations: list[dict[str, Any]] = []
        attempted = False
        for child_id, child_task in snapshot.tasks.items():
            if child_task.parent_task_id != task.task_id:
                continue
            attempted = True
            child_result = snapshot.results.get(child_id)
            if child_result is None:
                continue
            sources = child_result.output.get("sources", [])
            if not isinstance(sources, list):
                continue
            rule_id = str(child_task.context.get("monitor_rule_id", ""))
            observations.extend(
                {"rule_id": rule_id, "source": source}
                for source in sources
                if isinstance(source, dict)
            )
        return observations, attempted

    @staticmethod
    def _tool_observations(
        task: AgentTask,
        context: AgentExecutionContext,
    ) -> tuple[list[dict[str, Any]], bool]:
        artifacts = context.blackboard.get_artifacts(task.task_id)
        observations: list[dict[str, Any]] = []
        attempted = False
        for name, output in artifacts.items():
            if not name.startswith("github.read") or not isinstance(output, dict):
                continue
            attempted = True
            rule_id = str(output.get("rule_id") or "")
            items = output.get("items", [])
            if not isinstance(items, list):
                continue
            observations.extend(
                {"rule_id": rule_id, "source": item}
                for item in items
                if isinstance(item, dict)
            )
        return observations, attempted

    @staticmethod
    def _assign_observations(
        observations: list[dict[str, Any]],
        rules: list[MonitorRule],
    ) -> list[dict[str, Any]]:
        if not observations or not rules:
            return observations
        default_rule_id = rules[0].rule_id if len(rules) == 1 else ""
        assigned: list[dict[str, Any]] = []
        for item in observations:
            if isinstance(item.get("source"), dict):
                assigned.append(
                    {
                        "rule_id": item.get("rule_id") or default_rule_id,
                        "source": item["source"],
                    }
                )
            else:
                assigned.append({"rule_id": default_rule_id, "source": item})
        return assigned

    @staticmethod
    def _deduplicate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        for item in items:
            key = InformationMonitorGraphAgent._item_key(item)
            if key and key not in unique:
                unique[key] = item
        return list(unique.values())

    @staticmethod
    def _item_key(item: dict[str, Any]) -> str:
        return str(item.get("url") or item.get("title") or item).strip().lower()

    @staticmethod
    def _meaningfully_changed(
        previous: dict[str, Any],
        current: dict[str, Any],
        *,
        target_type: str,
    ) -> bool:
        if target_type != "github":
            return SQLiteMonitorStore.fingerprint(
                [previous]
            ) != SQLiteMonitorStore.fingerprint([current])
        previous_release = str(previous.get("latest_release") or "")
        current_release = str(current.get("latest_release") or "")
        if current_release and current_release != previous_release:
            return True
        if str(previous.get("snippet") or "") != str(current.get("snippet") or ""):
            return True
        previous_stars = int(previous.get("stars") or 0)
        current_stars = int(current.get("stars") or 0)
        star_delta = current_stars - previous_stars
        threshold = max(20, int(previous_stars * 0.01))
        return star_delta >= threshold

    @staticmethod
    def _infer_action(objective: str) -> str:
        text = objective.lower()
        if any(marker in text for marker in ["列出监控", "查看规则", "监控规则列表"]):
            return "list_rules"
        if any(marker in text for marker in ["删除监控", "取消监控", "停止监控"]):
            return "delete_rule"
        if any(marker in text for marker in ["创建监控", "添加监控", "订阅"]):
            return "create_rule"
        return "run_monitor"

    @staticmethod
    def _has_specific_target(objective: str) -> bool:
        compact = objective.strip()
        generic = {"检查监控更新", "查看监控", "运行监控", "监控更新"}
        generic_markers = ["我的监控", "全部监控", "已有监控"]
        return (
            bool(compact)
            and compact not in generic
            and not any(marker in compact for marker in generic_markers)
        )

    @staticmethod
    def _rule_from_payload(payload: dict[str, Any], objective: str) -> MonitorRule:
        target = str(payload.get("target") or objective).strip()
        query = str(payload.get("query") or objective).strip()
        target_type = str(payload.get("target_type") or "").strip()
        if not target_type:
            lowered = f"{target} {query}".lower()
            if "github" in lowered or "仓库" in lowered or "项目更新" in lowered:
                target_type = "github"
            elif "招聘" in lowered or "岗位" in lowered or "job" in lowered:
                target_type = "jobs"
            elif "博客" in lowered or "blog" in lowered:
                target_type = "tech_blog"
            elif "新闻" in lowered or "news" in lowered:
                target_type = "news"
            else:
                target_type = "company"
        deterministic_id = str(
            payload.get("rule_id")
            or uuid5(NAMESPACE_URL, f"pmaa-monitor:{target_type}:{target}:{query}")
        )
        return MonitorRule(
            rule_id=deterministic_id,
            name=str(payload.get("name") or target)[:80],
            target_type=target_type,
            target=target,
            query=query,
            enabled=bool(payload.get("enabled", True)),
            interval_minutes=int(payload.get("interval_minutes", 360)),
        )


# Compatibility alias for the previous adapter class name.
InformationMonitorAgent = InformationMonitorGraphAgent
