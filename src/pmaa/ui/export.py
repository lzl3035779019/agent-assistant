from collections.abc import Sequence
from typing import Any

from pmaa.storage.history_store import TaskHistoryRecord


def build_markdown_export(user_input: str, view: dict[str, Any]) -> str:
    answer = view.get("answer", "").strip()
    sections = [
        "# PMAA 任务报告",
        "",
        "## 用户问题",
        "",
        user_input.strip(),
        "",
        "## 最终回答",
        "",
        answer,
    ]

    if "资料来源" not in answer:
        sections.extend(["", _build_sources_section(view.get("sources", []))])

    sections.extend(
        [
            "",
            "## 执行摘要",
            "",
            _build_event_summary(view.get("events", [])),
            "",
            "## 反思检查",
            "",
            _build_reflection_summary(view.get("reflection", {})),
            "",
        ]
    )

    return "\n".join(section for section in sections if section is not None).strip() + "\n"


def build_bulk_markdown_export(records: Sequence[TaskHistoryRecord]) -> str:
    sections = [
        "# PMAA 批量任务导出",
        "",
        f"共导出 {len(records)} 个任务。",
        "",
    ]
    for index, record in enumerate(records, start=1):
        sections.extend(
            [
                f"## {record.title}",
                "",
                f"- 序号：{index}",
                f"- 任务 ID：{record.task_id}",
                f"- 创建时间：{record.created_at}",
                "",
                build_markdown_export(record.user_input, record.view).strip(),
                "",
            ]
        )
    return "\n".join(sections).strip() + "\n"


def _build_sources_section(sources: list[dict[str, Any]]) -> str:
    lines = ["## 资料来源", ""]
    if not sources:
        lines.append("- 未提供资料来源")
        return "\n".join(lines)

    for index, source in enumerate(sources, start=1):
        title = source.get("title", "未命名来源")
        url = source.get("url", "")
        if url:
            lines.append(f"- [S{index}] [{title}]({url})")
        else:
            lines.append(f"- [S{index}] {title}")
    return "\n".join(lines)


def _build_event_summary(events: list[dict[str, Any]]) -> str:
    if not events:
        return "- 未记录 Agent 执行事件"

    lines = []
    for index, event in enumerate(events, start=1):
        label = event.get("label") or event.get("agent") or "Agent"
        event_type = event.get("event_type", "unknown")
        lines.append(f"- {index}. {label} - {event_type}")
    return "\n".join(lines)


def _build_reflection_summary(reflection: dict[str, Any]) -> str:
    passed = bool(reflection.get("passed"))
    lines = [f"Reflection：{'通过' if passed else '未通过'}"]
    issues = reflection.get("issues") or []
    if issues:
        lines.append("")
        lines.append("问题：")
        lines.extend(f"- {issue}" for issue in issues)
    return "\n".join(lines)
