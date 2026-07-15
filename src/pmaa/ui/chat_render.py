import json
import re
from html import escape, unescape
from typing import Any


def build_thought_text(view: dict[str, Any] | None) -> str:
    if view is None:
        return "等待运行工作流。"
    lines: list[str] = []
    for index, event in enumerate(view.get("events", []), start=1):
        if _is_policy_event(event):
            lines.append(_format_policy_event(index, event))
            continue
        payload = json.dumps(event.get("output", {}), ensure_ascii=False)
        lines.append(
            f"[{index}] {event.get('label', event.get('agent', 'Agent'))} - "
            f"{event.get('event_type', 'completed')} {payload}"
        )
    return "\n".join(lines) or "暂无执行过程。"


def build_policy_card_markdown(view: dict[str, Any] | None) -> str:
    event = _find_policy_event(view)
    if event is None:
        return ""
    output = event.get("output", {})
    return "\n".join(
        [
            "#### 策略决策",
            "",
            f"- 意图：`{output.get('intent', 'unknown')}`",
            f"- 任务类型：`{output.get('task_kind', 'unknown')}`",
            f"- 执行模式：`{output.get('execution_mode', 'unknown')}`",
            f"- Memory 参与：`{_bool_label(output.get('need_memory'))}`",
            f"- 工具调用：`{_bool_label(output.get('need_tools'))}`",
            f"- 目标工具：`{output.get('required_tool', 'none')}`",
            f"- 复杂规划：`{_bool_label(output.get('should_plan'))}`",
            f"- 用户确认：`{_bool_label(output.get('requires_confirmation'))}`",
            f"- 风险等级：`{output.get('risk_level', 'low')}`",
            f"- 置信度：`{output.get('confidence', 0)}`",
            f"- 原因：{output.get('reason', '')}",
        ]
    )


def render_user_message(content: str) -> str:
    return f"""
    <div class="user-row">
      <div class="avatar user">U</div>
      <div class="question-card">{escape(content)}</div>
    </div>
    """


def render_assistant_message(
    content: str,
    view: dict[str, Any] | None = None,
    message_type: str = "normal",
) -> str:
    if message_type == "error":
        body = f'<div class="error-box">任务执行失败：{escape(content)}</div>'
    else:
        thought = ""
        if view is not None:
            policy_card = markdown_to_html(build_policy_card_markdown(view))
            thought = f"""
            <details class="thought-details" open>
              <summary>思考过程 / Agent 执行过程</summary>
              <div class="policy-card">{policy_card}</div>
              <pre>{escape(build_thought_text(view))}</pre>
            </details>
            """
        body = f"""
        <div class="answer-box">
          {thought}
          <div class="answer-content">{markdown_to_html(content)}</div>
        </div>
        """

    return f"""
    <div class="assistant-row">
      <div class="avatar assistant">A</div>
      {body}
    </div>
    """


def normalize_markdown_content(content: str) -> str:
    if "<div" not in content and "<details" not in content:
        return content
    text = re.sub(r"<details\b.*?</details>", "", content, flags=re.DOTALL)
    text = re.sub(r"<pre\b.*?</pre>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def markdown_to_html(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    html: list[str] = []
    in_list = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if in_list:
                html.append("</ul>")
                in_list = False
            continue

        if line.startswith("### "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h3>{_inline_markdown(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h2>{_inline_markdown(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h1>{_inline_markdown(line[2:])}</h1>")
        elif line.startswith(("- ", "* ")):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline_markdown(line[2:])}</li>")
        else:
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<p>{_inline_markdown(line)}</p>")

    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def _inline_markdown(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        escaped,
    )
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _find_policy_event(view: dict[str, Any] | None) -> dict[str, Any] | None:
    if view is None:
        return None
    for event in view.get("events", []):
        if _is_policy_event(event):
            return event
    return None


def _is_policy_event(event: dict[str, Any]) -> bool:
    output = event.get("output", {})
    return (
        event.get("agent") == "supervisor"
        and event.get("event_type") == "completed"
        and "intent" in output
        and "execution_mode" in output
    )


def _format_policy_event(index: int, event: dict[str, Any]) -> str:
    output = event.get("output", {})
    fields = [
        ("intent", output.get("intent", "unknown")),
        ("task_kind", output.get("task_kind", "unknown")),
        ("execution_mode", output.get("execution_mode", "unknown")),
        ("need_memory", _bool_label(output.get("need_memory"))),
        ("need_tools", _bool_label(output.get("need_tools"))),
        ("required_tool", output.get("required_tool", "none")),
        ("should_plan", _bool_label(output.get("should_plan"))),
        ("requires_confirmation", _bool_label(output.get("requires_confirmation"))),
        ("risk_level", output.get("risk_level", "low")),
        ("confidence", output.get("confidence", 0)),
        ("reason", output.get("reason", "")),
    ]
    detail = "\n".join(f"  {key}: {value}" for key, value in fields)
    return (
        f"[{index}] 策略决策 - {event.get('event_type', 'completed')}\n"
        f"{detail}"
    )


def _bool_label(value: object) -> str:
    return "是" if bool(value) else "否"
